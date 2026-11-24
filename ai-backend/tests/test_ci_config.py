"""The backend CI job must keep enough time to install ffmpeg before it runs pytest.

The hosted runner image has no ffmpeg and the caption tests cut audio with it. On 2026-11-24 a stalled
Ubuntu mirror spent 14:54 downloading the package and the 15-minute job cap killed the run inside the
install (run 45356658576), so pytest never started. The job now skips the install when ffmpeg exists,
retries the download and keeps a budget that fits a slow install plus the tests.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "utubot-ci.yml"


def job_block(name: str) -> list[str]:
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"  {name}:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    "):
            break
        block.append(line)
    return block


def step_block(job: list[str], name: str) -> list[str]:
    start = next(i for i, line in enumerate(job) if line.strip() == f"- name: {name}")
    block: list[str] = []
    for line in job[start + 1 :]:
        if line.strip().startswith("- name:"):
            break
        block.append(line)
    return block


def test_the_backend_job_has_room_for_ffmpeg_and_the_tests():
    job = job_block("backend")
    timeout = next(line for line in job if line.strip().startswith("timeout-minutes:"))
    minutes = int(timeout.split(":", 1)[1].strip())
    assert minutes >= 30, "a stalled apt download ate 15 minutes before pytest; keep the room"


def test_the_ffmpeg_install_skips_when_it_is_already_there_and_retries():
    run = "\n".join(step_block(job_block("backend"), "Install ffmpeg"))
    assert "command -v ffmpeg" in run, "do not spend the budget re-installing a present ffmpeg"
    assert "apt-get" in run and "no-install-recommends" in run
    assert "Acquire::Retries=3" in run, "a transient mirror failure must not fail the job"
