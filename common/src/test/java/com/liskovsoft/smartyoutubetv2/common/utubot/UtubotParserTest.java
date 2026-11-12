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
    public void aSummaryWithoutCaptionsCarriesTheOfferToTranscribe() throws Exception {
        Summary summary = UtubotParser.parseSummary("{\"video_id\":\"a\",\"prompt\":\"builtin/tldr\",\"status\":\"needs_transcript\"," +
                "\"transcript_status\":\"none\",\"can_transcribe\":true,\"message\":\"No captions. Transcribe the audio in the background?\"," +
                "\"estimate_s\":240,\"text\":null,\"error\":null}");

        assertTrue(summary.needsTranscript());
        assertTrue(summary.isTransient());
        assertFalse(summary.isPending());
        assertFalse(summary.isReady());
        assertTrue(summary.canTranscribe);
        assertEquals("No captions. Transcribe the audio in the background?", summary.message);
        assertEquals(240, summary.estimateSec);
        assertEquals(UtubotModels.UNKNOWN, summary.retryAfterSec);
        assertEquals(UtubotModels.UNKNOWN, summary.progressPercent);
    }

    @Test
    public void aSummaryThatCannotBeTranscribedSaysSo() throws Exception {
        Summary summary = UtubotParser.parseSummary("{\"status\":\"needs_transcript\",\"transcript_status\":\"none\"," +
                "\"can_transcribe\":false,\"message\":\"No captions are available for this video.\",\"estimate_s\":null}");

        assertTrue(summary.needsTranscript());
        assertFalse(summary.canTranscribe);
        assertEquals(UtubotModels.UNKNOWN, summary.estimateSec);
    }

    @Test
    public void aDelayedSummaryCarriesTheWaitAndItsReason() throws Exception {
        Summary summary = UtubotParser.parseSummary("{\"video_id\":\"a\",\"status\":\"pending\",\"transcript_status\":\"delayed\"," +
                "\"error\":\"YouTube is slowing us down\",\"retry_after_s\":45}");

        assertTrue(summary.isDelayed());
        assertTrue(summary.isPending());
        assertTrue(summary.isTransient());
        assertEquals(45, summary.retryAfterSec);
        assertEquals("YouTube is slowing us down", summary.error);
    }

    @Test
    public void aTranscribingSummaryCarriesItsProgressAsAPercentage() throws Exception {
        Summary summary = UtubotParser.parseSummary("{\"status\":\"pending\",\"transcript_status\":\"transcribing\",\"progress\":0.375," +
                "\"estimate_s\":180}");

        assertTrue(summary.isTranscribing());
        assertTrue(summary.isTransient());
        assertEquals(38, summary.progressPercent);
        assertEquals(180, summary.estimateSec);
    }

    @Test
    public void aSummaryOfAnOlderBackendHasNoTranscriptState() throws Exception {
        Summary summary = UtubotParser.parseSummary("{\"video_id\":\"a\",\"status\":\"ready\",\"text\":\"- one\"}");

        assertNull(summary.transcriptStatus);
        assertFalse(summary.isTransient());
        assertTrue(summary.isReady());
        assertEquals(UtubotModels.UNKNOWN, summary.estimateSec);
    }

    @Test
    public void aTranscriptStateTakesTheTranscriptStatusOverTheJobStatus() throws Exception {
        UtubotModels.Transcript running = UtubotParser.parseTranscript("{\"video_id\":\"a\",\"status\":\"queued\"," +
                "\"transcript_status\":\"transcribing\",\"progress\":0.5,\"estimate_s\":240,\"job_id\":\"j\"}");
        UtubotModels.Transcript done = UtubotParser.parseTranscript("{\"video_id\":\"a\",\"transcript_status\":\"ok\",\"source\":\"asr\"}");
        UtubotModels.Transcript failed = UtubotParser.parseTranscript("{\"transcript_status\":\"failed\",\"error\":\"transcription failed\"}");
        UtubotModels.Transcript jobOnly = UtubotParser.parseTranscript("{\"status\":\"running\",\"progress\":1}");
        UtubotModels.Transcript unknown = UtubotParser.parseTranscript("{\"video_id\":\"a\",\"transcript_status\":\"unknown\"}");

        assertTrue(running.isTranscribing());
        assertEquals(50, running.progressPercent);
        assertEquals(240, running.estimateSec);
        assertTrue(done.isDone());
        assertFalse(done.isTranscribing());
        assertTrue(failed.isFailed());
        assertEquals("transcription failed", failed.error);
        assertTrue(jobOnly.isTranscribing());
        assertEquals(100, jobOnly.progressPercent);
        assertFalse(unknown.isDone() || unknown.isTranscribing() || unknown.isFailed());
    }

    @Test
    public void progressIsAFractionAndAPercentageAboveOne() throws Exception {
        assertEquals(0, UtubotParser.parseTranscript("{\"progress\":0}").progressPercent);
        assertEquals(100, UtubotParser.parseTranscript("{\"progress\":1.0}").progressPercent);
        assertEquals(42, UtubotParser.parseTranscript("{\"progress\":42}").progressPercent);
        assertEquals(100, UtubotParser.parseTranscript("{\"progress\":150}").progressPercent);
        assertEquals(UtubotModels.UNKNOWN, UtubotParser.parseTranscript("{\"progress\":null}").progressPercent);
        assertEquals(UtubotModels.UNKNOWN, UtubotParser.parseTranscript("{\"progress\":-1}").progressPercent);
        assertEquals(UtubotModels.UNKNOWN, UtubotParser.parseTranscript("{}").progressPercent);
    }

    @Test
    public void aFailedAnswerKeepsItsReasonAndTheOfferToTryAgain() throws Exception {
        Summary video = UtubotParser.parseSummary("{\"status\":\"failed\",\"transcript_status\":\"failed\",\"error\":\"This video is private\"," +
                "\"reason\":\"private\",\"can_transcribe\":false}");
        Summary job = UtubotParser.parseSummary("{\"status\":\"failed\",\"transcript_status\":\"failed\",\"error\":\"transcription failed\"," +
                "\"can_transcribe\":true}");
        Summary model = UtubotParser.parseSummary("{\"status\":\"failed\",\"error\":\"the language model request failed\"}");

        assertEquals("private", video.reason);
        assertFalse(video.canTranscribe);
        assertNull(job.reason);
        assertTrue(job.canTranscribe);
        assertFalse("no offer without the field outside a video without captions", model.canTranscribe);
    }

    @Test
    public void anInsightCarriesTheTranscriptStateToo() throws Exception {
        Insight needs = UtubotParser.parseInsight("{\"video_id\":\"a\",\"status\":\"needs_transcript\",\"transcript_status\":\"none\"," +
                "\"can_transcribe\":true,\"message\":\"No captions. Transcribe the audio in the background?\",\"estimate_s\":600}");
        Insight delayed = UtubotParser.parseInsight("{\"status\":\"pending\",\"transcript_status\":\"delayed\",\"error\":\"slow\",\"retry_after_s\":90}");
        Insight ready = UtubotParser.parseInsight("{\"status\":\"ready\",\"transcript_status\":\"ok\",\"answer\":\"Yes.\",\"source\":\"asr\"}");

        assertTrue(needs.needsTranscript());
        assertTrue(needs.canTranscribe);
        assertEquals(600, needs.estimateSec);
        assertTrue(delayed.isDelayed());
        assertEquals(90, delayed.retryAfterSec);
        assertFalse(ready.isTransient());
        assertEquals("asr", ready.source);
        assertEquals("Yes.", ready.answer);
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
    public void parsesThePanelDefaultNextToTheDefault() throws Exception {
        PromptList list = UtubotParser.parsePrompts("{\"default\":\"builtin/tldr\",\"panel_default\":\"builtin/glance\",\"sets\":[" +
                "{\"id\":\"builtin\",\"name\":\"Built-in\",\"prompts\":[{\"id\":\"tldr\",\"key\":\"builtin/tldr\",\"label\":\"TL;DR\"}," +
                "{\"id\":\"glance\",\"key\":\"builtin/glance\",\"label\":\"Glance\"}]}]}");

        assertEquals("builtin/tldr", list.defaultKey);
        assertEquals("builtin/glance", list.panelDefaultKey);
        assertEquals("TL;DR", list.first().label);
    }

    @Test
    public void anOlderBackendHasNoPanelDefault() throws Exception {
        PromptList list = UtubotParser.parsePrompts("{\"default\":\"builtin/tldr\",\"sets\":[]}");
        PromptList explicitNull = UtubotParser.parsePrompts("{\"default\":\"builtin/tldr\",\"panel_default\":null,\"sets\":[]}");

        assertNull(list.panelDefaultKey);
        assertNull(explicitNull.panelDefaultKey);
        assertNull(list.first());
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
