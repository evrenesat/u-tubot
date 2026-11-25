import json

from utubot.captions.gate import GATE_VERSION, check_attestation, compare
from utubot.cli import main
from utubot.config import CaptionsConfig


def report(
    hit=0.9, loose=0.95, within=0.95, short=0, meaning=0.8, median=0.1, p95=0.5, passed=True
):
    return {
        "overall": {"hit": hit, "loose": loose, "median_s": median, "p95_s": p95},
        "words": {"within_s": within},
        "track": {"short_cues": short},
        "meaning": {"score": meaning, "passed": passed},
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
    assert "does not beat the baseline" in joined


def test_missing_meaning_is_a_failure():
    candidate = report()
    baseline = report()
    candidate["meaning"] = None
    result = compare(candidate, baseline, CaptionsConfig())
    assert not result["passed"] and "meaning was not measured for both tracks" in result["failures"]


def test_a_worse_cue_offset_tail_is_a_failure():
    result = compare(
        report(median=0.6, p95=1.4),
        report(median=0.1, p95=0.5),
        CaptionsConfig(),
    )
    joined = " | ".join(result["failures"])
    assert not result["passed"]
    assert "median offset" in joined and "p95 offset" in joined


def test_missing_cue_offsets_are_failures():
    candidate = report()
    baseline = report()
    candidate["overall"].pop("median_s")
    candidate["overall"].pop("p95_s")
    result = compare(candidate, baseline, CaptionsConfig())
    joined = " | ".join(result["failures"])
    assert "median offset was not measured" in joined
    assert "p95 offset was not measured" in joined


def test_meaning_must_beat_the_baseline_not_just_match_it():
    result = compare(report(meaning=0.8), report(meaning=0.8), CaptionsConfig())
    assert not result["passed"] and "does not beat the baseline" in " | ".join(result["failures"])


def test_meaning_under_the_floor_fails():
    result = compare(
        report(meaning=0.4, passed=False), report(meaning=0.3, passed=True), CaptionsConfig()
    )
    assert not result["passed"]
    assert "meaning 0.400 is under the 0.500 floor" in result["failures"]


def test_an_attestation_must_be_current_and_passed(tmp_path):
    from utubot.captions.gate import write_attestation

    path = tmp_path / "gate.json"
    assert "no gate attestation" in check_attestation(None)
    assert check_attestation(path) is not None
    write_attestation(path, {"version": GATE_VERSION, "passed": False, "failures": ["x"]})
    assert "did not pass" in check_attestation(path)
    write_attestation(path, {"version": GATE_VERSION, "passed": True, "failures": []})
    assert check_attestation(path) is None


def test_the_cli_reads_two_reports_and_returns_a_status(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n[[users]]\nname = "owner"\nadmin = true\n'
    )
    candidate = tmp_path / "candidate.json"
    baseline = tmp_path / "baseline.json"
    candidate.write_text(json.dumps(report()))
    baseline.write_text(json.dumps(report(hit=0.6, loose=0.8, meaning=0.7)))
    attestation = tmp_path / "gate.json"
    code = main(
        [
            "--config",
            str(config),
            "captions-gate",
            "--candidate",
            str(candidate),
            "--baseline",
            str(baseline),
            "--attestation",
            str(attestation),
        ]
    )
    assert code == 0 and "PASS" in capsys.readouterr().out
    assert check_attestation(attestation) is None
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
            "--attestation",
            str(attestation),
        ]
    )
    assert code == 1 and "FAIL" in capsys.readouterr().out
    assert "did not pass" in check_attestation(attestation)
