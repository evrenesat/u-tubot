package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotParserTest {
    private static final String ASSESS = "{\"results\":[" +
            "{\"video_id\":\"a\",\"status\":\"ready\",\"action\":\"hide\",\"mark_label\":\"Clickbait · 12m≈2m\"," +
            "\"flags\":[{\"kind\":\"clickbait\",\"label\":\"Clickbait\",\"severity\":0.8,\"reason\":\"vague\"}]," +
            "\"title_question\":\"Does X work?\",\"answer_short\":\"Yes, since v3.\",\"insight_ready\":true,\"captions_ready\":false,\"future\":1}," +
            "{\"video_id\":\"b\",\"status\":\"pending\",\"action\":\"none\",\"mark_label\":null,\"flags\":[],\"title_question\":null,\"answer_short\":null}" +
            "]}";

    @Test
    public void parsesAssessVerdicts() throws Exception {
        List<Verdict> verdicts = UtubotParser.parseAssess(ASSESS);

        assertEquals(2, verdicts.size());
        Verdict first = verdicts.get(0);
        assertEquals("a", first.videoId);
        assertTrue(first.isReady());
        assertEquals("hide", first.action);
        assertEquals("Clickbait · 12m≈2m", first.markLabel);
        assertEquals(1, first.flags.size());
        assertEquals(0.8, first.flags.get(0).severity, 0.001);
        assertEquals("Yes, since v3.", first.answerShort);
        assertTrue(first.insightReady);
        assertFalse(first.captionsReady);

        Verdict second = verdicts.get(1);
        assertFalse(second.isReady());
        assertNull(second.markLabel);
        assertNull(second.answerShort);
    }

    @Test
    public void missingFieldsKeepDefaults() throws Exception {
        List<Verdict> verdicts = UtubotParser.parseAssess("{\"results\":[{\"video_id\":\"x\"}]}");

        assertEquals("pending", verdicts.get(0).status);
        assertEquals("none", verdicts.get(0).action);
        assertTrue(verdicts.get(0).flags.isEmpty());
    }

    @Test
    public void parsesInsight() throws Exception {
        Insight insight = UtubotParser.parseInsight("{\"video_id\":\"a\",\"status\":\"ready\",\"error\":null,\"title_question\":\"Q?\"," +
                "\"answer\":\"Two sentences.\",\"answer_confidence\":0.9,\"summary\":\"S\",\"key_points\":[\"p1\",\"p2\"]," +
                "\"inflation\":{\"duration_s\":754,\"essential_s\":120,\"ratio\":0.16},\"source\":\"asr\"}");

        assertFalse(insight.isPending());
        assertEquals("Two sentences.", insight.answer);
        assertEquals(2, insight.keyPoints.size());
        assertEquals(120, insight.inflation.essentialSec);
        assertEquals("asr", insight.source);
        assertNull(insight.error);
    }

    @Test
    public void parsesSummary() throws Exception {
        Summary pending = UtubotParser.parseSummary("{\"video_id\":\"a\",\"prompt\":\"s/p\",\"status\":\"pending\",\"text\":null}");
        Summary ready = UtubotParser.parseSummary("{\"video_id\":\"a\",\"prompt\":\"s/p\",\"status\":\"ready\",\"text\":\"- one\",\"source\":\"youtube_captions\"}");

        assertTrue(pending.isPending());
        assertNull(pending.text);
        assertFalse(ready.isPending());
        assertEquals("- one", ready.text);
        assertEquals("youtube_captions", ready.source);
    }

    @Test
    public void parsesPromptSets() throws Exception {
        PromptList list = UtubotParser.parsePrompts("{\"default\":\"demo/tldr\",\"sets\":[" +
                "{\"id\":\"builtin\",\"name\":\"Built-in\",\"version\":\"1\",\"source_url\":null,\"prompts\":[{\"id\":\"short\",\"key\":\"builtin/short\",\"label\":\"Short\",\"default\":false}]}," +
                "{\"id\":\"demo\",\"name\":\"Demo\",\"version\":\"2026-11-12\",\"source_url\":\"https://x/p.json\"," +
                "\"prompts\":[{\"id\":\"tldr\",\"key\":\"demo/tldr\",\"label\":\"TL;DR\",\"default\":true},{\"id\":\"deep\",\"label\":\"Deep\"}]}]}");

        assertEquals("demo/tldr", list.defaultKey);
        assertEquals(2, list.sets.size());
        assertEquals(3, list.allPrompts().size());
        assertEquals("https://x/p.json", list.sets.get(1).sourceUrl);
        assertNull(list.sets.get(0).sourceUrl);
        assertEquals("TL;DR", list.find("demo/tldr").label);
        assertEquals("demo/deep", list.find("demo/deep").key);
        assertNull(list.find("nope/none"));
    }

    @Test
    public void parsesCaptions() throws Exception {
        Captions captions = UtubotParser.parseCaptions("{\"status\":\"ready\",\"progress\":1.0,\"tracks\":[" +
                "{\"lang\":\"en\",\"label\":\"English\",\"url\":\"/v1/videos/a/captions/en.vtt\",\"speakers\":2},{\"lang\":\"tr\",\"label\":\"Turkish\"}]}");

        assertTrue(captions.isReady());
        assertEquals(1, captions.tracks.size());
        assertEquals(2, captions.tracks.get(0).speakers);

        assertFalse(UtubotParser.parseCaptions("{\"status\":\"running\",\"progress\":0.4,\"tracks\":[]}").isReady());
        assertFalse(UtubotParser.parseCaptions("{\"status\":\"none\"}").isReady());
    }

    @Test
    public void parsesMe() throws Exception {
        Me me = UtubotParser.parseMe("{\"user\":\"owner\",\"policy\":{},\"features\":{\"assess\":true,\"insight\":false,\"captions\":true}}");

        assertEquals("owner", me.user);
        assertTrue(me.assess);
        assertFalse(me.insight);
        assertTrue(me.captions);
    }
}
