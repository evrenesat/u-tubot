from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from . import appchannel, appsync
from .auth import Auth, PairError, append_user, hash_token, new_token
from .config import load_config
from .db import Database
from .prompts import PromptError, validate_prompt_set
from .webauth import WebAuth


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    cfg = load_config(args.config)
    uvicorn.run(
        "utubot.app:app_factory",
        factory=True,
        host=args.host or cfg.server.host,
        port=args.port or cfg.server.port,
    )
    return 0


def cmd_user_add(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    token = new_token()
    try:
        append_user(cfg.users_path, args.name, hash_token(token), admin=args.admin)
    except PairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"user: {args.name}")
    print(f"token: {token}")
    print(f"hash stored in {cfg.users_path}; the token is not stored and cannot be shown again")
    return 0


def _auth(args: argparse.Namespace) -> Auth:
    cfg = load_config(args.config)
    return Auth(cfg, Database(cfg.db_path))


def cmd_user_passwd(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db = Database(cfg.db_path)
    web = WebAuth(cfg, db, Auth(cfg, db))
    if args.stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass(f"New password for {args.name}: ")
        if getpass.getpass("Repeat it: ") != password:
            print("error: the two entries differ", file=sys.stderr)
            return 1
    try:
        web.set_password(args.name, password)
    except PairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"password set for {args.name}; their web sessions were signed out")
    return 0


def cmd_user_pair(args: argparse.Namespace) -> int:
    try:
        code, ttl = _auth(args).create_pair_code(args.name)
    except PairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"pairing code for {args.name}: {code}")
    print(f"valid for {ttl // 60} minutes, single use")
    return 0


def cmd_user_devices(args: argparse.Namespace) -> int:
    for dev in _auth(args).list_devices(args.name):
        print(f"{dev['id']}  {dev['user']}  {dev['device']}")
    return 0


def cmd_user_revoke(args: argparse.Namespace) -> int:
    if not _auth(args).revoke(args.device_id):
        print("unknown device id", file=sys.stderr)
        return 1
    print("revoked")
    return 0


def cmd_app_publish(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    changelog = [line.strip() for line in args.changelog.splitlines() if line.strip()]
    try:
        manifest = appchannel.publish(
            cfg,
            [Path(a) for a in args.apk],
            args.version_name,
            args.version_code,
            changelog,
            args.abi,
        )
    except appchannel.PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"published {args.version_name} ({args.version_code}); manifest: {manifest}")
    return 0


def cmd_app_sync_github(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    repo = args.repo or cfg.app.github_repo
    if not repo:
        print("error: give --repo OWNER/NAME or set [app] github_repo", file=sys.stderr)
        return 1
    try:
        result = appsync.sync_github(
            cfg, repo, include_prerelease=args.prerelease, dry_run=args.dry_run
        )
    except appsync.TransientError as exc:
        print(f"warning: {exc}; will retry on the next run", file=sys.stderr)
        if not args.dry_run:
            appchannel.record_sync(cfg, "unreachable", error=str(exc))
        return appsync.EXIT_TEMPFAIL
    except appsync.SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if not args.dry_run:
            appchannel.record_sync(cfg, "error", error=str(exc))
        return 1
    if not args.dry_run:
        appchannel.record_sync(cfg, result.status, result.version_name)
    prefix = "dry run: " if args.dry_run else ""
    for line in result.lines:
        print(f"{prefix}{line}")
    return 0


def cmd_youtube_record(args: argparse.Namespace) -> int:
    """Record one video's YouTube answers into a cassette. The owner runs this by hand.

    It is the only u-tubot command that reaches YouTube: never run it from tests, CI or an
    agent's verification runs. Cassettes replay in tests and in the offline dev-proxy mode.
    """
    import asyncio

    from .videoref import VIDEO_ID_RE
    from .youtube_fixtures import fixture_dir, record_cassette

    if not VIDEO_ID_RE.match(args.video_id):
        print(
            f"youtube-record failed: {args.video_id!r} is not an 11-character YouTube video id",
            file=sys.stderr,
        )
        return 1
    cfg = load_config(args.config)
    try:
        target = asyncio.run(
            record_cassette(
                cfg,
                args.video_id,
                lang=args.lang,
                out_dir=Path(args.out) if args.out else None,
                note=args.note,
            )
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"youtube-record failed: {exc}", file=sys.stderr)
        return 1
    print(f"recorded {target} ({fixture_dir(cfg)})")
    print("check it in: no signed URL may appear in the file (the recorder strips them)")
    return 0


def cmd_prompts_validate(args: argparse.Namespace) -> int:
    try:
        with open(args.file, encoding="utf-8") as fh:
            data = json.load(fh)
        pset = validate_prompt_set(data)
    except (OSError, json.JSONDecodeError, PromptError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"ok: set '{pset.id}' with {len(pset.prompts)} prompts")
    for prompt in pset.prompts:
        print(f"  {pset.id}/{prompt.id}  {prompt.label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="utubot")
    parser.add_argument("--config", help="path to config TOML (default: $UTUBOT_CONFIG)")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)
    user = sub.add_parser("user", help="manage users").add_subparsers(dest="sub", required=True)
    add = user.add_parser("add", help="create a user and print a new token once")
    add.add_argument("name")
    add.add_argument("--admin", action="store_true", help="mark the user as admin")
    add.set_defaults(func=cmd_user_add)
    passwd = user.add_parser("passwd", help="set a user's web sign-in password")
    passwd.add_argument("name")
    passwd.add_argument(
        "--stdin", action="store_true", help="read the password from stdin (one line), no prompt"
    )
    passwd.set_defaults(func=cmd_user_passwd)
    pair = user.add_parser("pair", help="create a one-time pairing code for a user")
    pair.add_argument("name")
    pair.set_defaults(func=cmd_user_pair)
    devices = user.add_parser("devices", help="list paired device tokens")
    devices.add_argument("name", nargs="?")
    devices.set_defaults(func=cmd_user_devices)
    revoke = user.add_parser("revoke", help="revoke a paired device token")
    revoke.add_argument("device_id")
    revoke.set_defaults(func=cmd_user_revoke)
    app = sub.add_parser("app", help="app update channel").add_subparsers(dest="sub", required=True)
    publish = app.add_parser(
        "publish", help="publish APKs (one per ABI, named ..._<abi>.apk) and rewrite update.json"
    )
    publish.add_argument("apk", nargs="+")
    publish.add_argument("--abi", help="ABI of a single APK whose name does not say it")
    publish.add_argument("--version-name", required=True)
    publish.add_argument("--version-code", type=int, required=True)
    publish.add_argument("--changelog", default="")
    publish.set_defaults(func=cmd_app_publish)
    sync = app.add_parser(
        "sync-github",
        help="publish the newest GitHub Release of the app into the update channel",
    )
    sync.add_argument("--repo", help="OWNER/NAME (default: [app] github_repo)")
    sync.add_argument(
        "--prerelease", action="store_true", help="consider releases marked as prereleases"
    )
    sync.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would happen; download no APK, write nothing",
    )
    sync.set_defaults(func=cmd_app_sync_github)
    prompts = sub.add_parser("prompts", help="prompt set tools").add_subparsers(
        dest="sub", required=True
    )
    validate = prompts.add_parser("validate", help="validate a prompt set JSON file")
    validate.add_argument("file")
    validate.set_defaults(func=cmd_prompts_validate)
    record = sub.add_parser(
        "youtube-record",
        help=(
            "record one video's YouTube answers into a replay fixture (owner only: this is the"
            " one command that reaches YouTube; never run it from tests, CI or agent checks)"
        ),
    )
    record.add_argument("video_id", help="the 11-character YouTube video id")
    record.add_argument(
        "--lang", help="prefer this caption language (default: [transcripts] default_language)"
    )
    record.add_argument("--out", help="write the cassette here (default: the fixtures directory)")
    record.add_argument("--note", help="a note stored in the cassette, e.g. why it was recorded")
    record.set_defaults(func=cmd_youtube_record)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
