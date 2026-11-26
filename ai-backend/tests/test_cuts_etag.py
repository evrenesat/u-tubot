from __future__ import annotations

import pytest

from tests.conftest import TOKEN
from tests.test_cuts_api import post_cut, set_transcript, wait_ready
from utubot.config import LLMTask

VID = "abcdefghijk"


@pytest.fixture
async def cuts_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    return env


async def build_ready(env, preset="cut-demo"):
    """A single ready cut, so the list has cached data to validate."""
    set_transcript(env.fetcher)
    env.llm.cut_answer = {
        "parts": [{"from": 1, "to": 3, "label": "The demo"}],
        "summary": "s",
        "kept_s": 10,
    }
    row = await post_cut(env, preset=preset)
    return await wait_ready(env, row.json()["request_id"])


class TestCutsEtag:
    async def test_listCarriesAStrongEtagAndALongCacheLifetime(self, cuts_env):
        await build_ready(cuts_env)

        r = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )

        assert r.status_code == 200, r.text
        etag = r.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"')  # a strong validator, not a weak W/ one
        assert "max-age=" in r.headers["cache-control"]
        assert r.json()["etag"] == etag

    async def test_revalidatingWithTheStoredEtagReturns304(self, cuts_env):
        first = await build_ready(cuts_env)

        list_r = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        etag = list_r.headers["etag"]

        again = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts",
            headers={"Authorization": f"Bearer {TOKEN}", "If-None-Match": etag},
        )

        assert again.status_code == 304
        assert again.headers["etag"] == etag  # the 304 still carries the validator
        # The ready cut in the list keeps its own strong ETag, so the client can cache the parts too.
        assert first["cut"]["preset_id"] == "cut-demo"

    async def testTheListEtagIsStableWithoutAConditionalRequest(self, cuts_env):
        await build_ready(cuts_env)

        first = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        second = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )

        assert first.headers["etag"] == second.headers["etag"]

    async def testASecondReadyCutChangesTheListEtag(self, cuts_env):
        await build_ready(cuts_env, preset="cut-demo")
        old = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )

        await build_ready(cuts_env, preset="cut-no-filler")
        new = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )

        assert new.headers["etag"] != old.headers["etag"]
        # The stored (now stale) ETag no longer matches: the list was served again, not 304'd.
        stale = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts",
            headers={"Authorization": f"Bearer {TOKEN}", "If-None-Match": old.headers["etag"]},
        )
        assert stale.status_code == 200
        assert stale.headers["etag"] == new.headers["etag"]

    async def testAFailedBuildKeepsTheReadyCutInTheList(self, cuts_env):
        await build_ready(cuts_env, preset="cut-demo")
        old = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        old_presets = {p["id"]: p for p in old.json()["presets"]}

        # A second preset that fails validation: the still-ready cut stays in the list unchanged.
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {"parts": [{"from": 40, "to": 99}]}
        row = await post_cut(cuts_env, preset="cut-no-filler")
        assert (await wait_ready(cuts_env, row.json()["request_id"]))["state"] == "failed"

        again = await cuts_env.client.get(
            f"/v1/videos/{VID}/cuts", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        again_presets = {p["id"]: p for p in again.json()["presets"]}

        assert again_presets["cut-demo"]["state"] == "ready"
        assert again_presets["cut-demo"]["cut"] == old_presets["cut-demo"]["cut"]
        # The failed preset is now shown as failed, so the list validator moved even though the cut did not.
        assert again.headers["etag"] != old.headers["etag"]
