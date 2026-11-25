import json

from utubot.captions.gate import compare
from utubot.cli import main
from utubot.config import CaptionsConfig


def report(hit=0.9, loose=0.95, within=0.95, short=0, meaning=0.8):
    return {
        "overall": {"hit": hit, "loose": loose},
        "words": {"within_s": within},
        "track": {"short_cues": short},
        "meaning": {"score": meaning},
    }


def test_a_track_that_beats_the_baseline_passes():
    result = compare(report(), report(hit=0.6, loose=0.8, meaning=0.7), CaptionsConfig())
    assert result["passed"] and result["failures"] == []
    assert result["candidate"]["hit"] == 0.9


def test_every_failed_check_is_named():
    result = compare(
        report(hit=0.65, loose=0.9, within=0.7, short=3, meaning=0.6),
        report(hit=0.6, loose=0.85, meaning=0.6),
        CaptionsConfig(),
    )
    assert not result["passed"]
    joined = " | ".join(result["failures"])
    assert "not 0.200 over the baseline" in joined
    assert "word within" in joined
    assert "cues are under" in joined


def test_missing_meaning_is_a_failure():
    candidate = report()
    baseline = report()
    candidate["meaning"] = None
    result = compare(candidate, baseline, CaptionsConfig())
    assert not result["passed"] and "meaning was not measured for both tracks" in result["failures"]


def test_the_cli_reads_two_reports_and_returns_a_status(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n[[users]]\nname = "owner"\nadmin = true\n'
    )
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    candidate.write_text(json.dumps(report()))
    baseline.write_text(json.dumps(report(hit=0.6, loose=0.8, meaning=0.7)))
    code = main(
        [
            "--config",
            str(config),
            "captions-gate",
            "--candidate",
            str(candidate),
            "--baseline",
            str(baseline),
        ]
    )
    assert code == 0 and "PASS" in capsys.readouterr().out
    baseline.write_text(json.dumps(report(hit=0.95, loose=0.99, meaning=0.9)))
    code = main(
        [
            "--config",
            str(config),
            "captions-gate",
            "--candidate",
            str(candidate),
            "--baseline",
            str(baseline),
        ]
    )
    assert code == 1 and "FAIL" in capsys.readouterr().out
