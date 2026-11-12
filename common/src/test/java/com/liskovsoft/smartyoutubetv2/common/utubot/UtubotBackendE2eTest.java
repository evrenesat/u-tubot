package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPolicy.Decision;

import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * The client against a running backend (the real server with a mock LLM behind it). Skipped unless UTUBOT_E2E_URL and
 * UTUBOT_E2E_CODE (a fresh pairing code) are set.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotBackendE2eTest {
    private static final String URL_ENV = "UTUBOT_E2E_URL";
    private static final String CODE_ENV = "UTUBOT_E2E_CODE";
    private static final int WAIT_MS = 3000;
    private static final int HARD_TIMEOUT_MS = 5000;
    private static final int SUMMARY_WAIT_MS = 20000;
    private static final String VIDEO_ID = "aaaaaaaaaaa";

    private UtubotClient mClient;

    @Before
    public void pair() throws Exception {
        String url = System.getenv(URL_ENV);
        String code = System.getenv(CODE_ENV);
        Assume.assumeTrue(url != null && code != null);

        assertTrue(new UtubotClient(url, "").health());
        UtubotClient.PairResult paired = new UtubotClient(url, "").pair(code, "e2e device");
        assertTrue(paired.token.startsWith("utb_"));
        mClient = new UtubotClient(url, paired.token);
    }

    @Test
    public void meAssessPromptsSummaryAndCaptions() throws Exception {
        Me me = mClient.me();
        assertEquals("owner", me.user);

        List<Verdict> verdicts = mClient.assess(Arrays.asList(meta("bbbbbbbbbbb", "CLICKBAIT you will not believe it"),
                meta("ccccccccccc", "Reaction videos pile"), meta("ddddddddddd", "A calm tutorial")), UtubotPolicy.SECTION_HOME, WAIT_MS, HARD_TIMEOUT_MS);

        assertEquals(3, verdicts.size());
        assertEquals(Decision.MARK, UtubotPolicy.decide(verdicts.get(0), false));
        assertFalse(UtubotPolicy.markLabel(verdicts.get(0)).isEmpty());
        assertEquals(Decision.HIDE, UtubotPolicy.decide(verdicts.get(1), false));
        assertEquals(Decision.MARK, UtubotPolicy.decide(verdicts.get(1), true));
        assertEquals(Decision.SHOW, UtubotPolicy.decide(verdicts.get(2), false));

        PromptList prompts = mClient.prompts();
        assertFalse(prompts.allPrompts().isEmpty());
        mClient.setDefaultPrompt(prompts.allPrompts().get(0).key);
        assertEquals(prompts.allPrompts().get(0).key, mClient.prompts().defaultKey);

        Summary summary = mClient.summary(VIDEO_ID, null, meta(VIDEO_ID, "Does it work?"), SUMMARY_WAIT_MS);
        assertNotNull(summary.status);

        Captions captions = mClient.captions(VIDEO_ID);
        assertNotNull(captions.status);
    }

    private static VideoMeta meta(String id, String title) {
        VideoMeta meta = new VideoMeta();
        meta.videoId = id;
        meta.title = title;
        meta.channel = "Chan";
        meta.durationSec = 900;
        return meta;
    }
}
