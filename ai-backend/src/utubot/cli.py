from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import appchannel
from .auth import Auth, PairError, append_user, hash_token, new_token
from .config import load_config
from .db import Database
from .prompts import PromptError, validate_prompt_set


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
    append_user(cfg.users_path, args.name, hash_token(token), admin=args.admin)
    print(f"user: {args.name}")
    print(f"token: {token}")
    print(f"hash stored in {cfg.users_path}; the token is not stored and cannot be shown again")
    return 0


def _auth(args: argparse.Namespace) -> Auth:
    cfg = load_config(args.config)
    return Auth(cfg, Database(cfg.db_path))


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
    prompts = sub.add_parser("prompts", help="prompt set tools").add_subparsers(
        dest="sub", required=True
    )
    validate = prompts.add_parser("validate", help="validate a prompt set JSON file")
    validate.add_argument("file")
    validate.set_defaults(func=cmd_prompts_validate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
