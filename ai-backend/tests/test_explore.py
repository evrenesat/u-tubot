from __future__ import annotations

import textwrap

from utubot.config import load_config

CFG = """
[server]
host = "127.0.0.1"
port = 8000

[auth]
token = "tok123"

[llm]
model = "test"
retries_on_bad_json = 0

[llm.cuts]
model = "cutmodel"

[llm.cuts_vision]
model = "visionmodel"

[llm.triage]
model = "triagemodel"
"""


def test_load_config_tags_cut_features(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(CFG))
    cfg = load_config(str(p))
    print("cuts.feature =", cfg.llm.cuts.feature)
    print("cuts_vision.feature =", cfg.llm.cuts_vision.feature)
    print("triage.feature =", cfg.llm.triage.feature)
    assert cfg.llm.cuts is not None
    assert cfg.llm.cuts.feature == "cuts"
    assert cfg.llm.cuts_vision is not None
    assert cfg.llm.cuts_vision.feature == "cuts_vision"
    assert cfg.llm.triage.feature == "triage"
