package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutMode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutsParserTest {
    private static final String CUT = "{\"version\":1,\"video_id\":\"abcdefghijk\",\"transcript_hash\":\"t1\"," +
            "\"duration_ms\":240000,\"label\":\"No filler\",\"summary\":\"The demo and the result.\"," +
            "\"parts\":[{\"label\":\"Start\",\"start_ms\":0,\"end_ms\":60000},{\"label\":\"End\",\"start_ms\":108000,\"end_ms\":240000}]," +
            "\"skip_ranges_ms\":[[60000,108000]],\"kept_ms\":192000,\"source\":\"youtube_captions\"," +
            "\"preset_id\":\"cut-no-filler\",\"model\":\"fast\",\"built_at\":\"2026-11-20T10:00:00Z\"}";

    private static final String NEW_CUT = "{\"version\":1,\"video_id\":\"abcdefghijk\",\"transcript_hash\":\"t1\"," +
            "\"duration_ms\":240000,\"label\":\"No filler\",\"summary\":\"The demo and the result.\"," +
            "\"parts\":[{\"label\":\"Start\",\"start_ms\":0,\"end_ms\":60000},{\"label\":\"End\",\"start_ms\":108000,\"end_ms\":240000}]," +
            "\"skip_ranges_ms\":[[60000,108000]],\"kept_ms\":192000," +
            "\"source\":{\"kind\":\"youtube\",\"key\":\"youtube:abcdefghijk\"}," +
            "\"transitions\":[{\"after_part\":0,\"type\":\"dip\",\"duration_ms\":300," +
            "\"asset\":{\"ref\":\"cut-assets/1\",\"sha256\":\"abc\"},\"engine\":\"ffmpeg\"," +
            "\"engine_version\":\"7\",\"status\":\"ready\"}],\"mode\":\"quick\"," +
            "\"preset_id\":\"cut-no-filler\",\"model\":\"fast\",\"built_at\":\"2026-11-20T10:00:00Z\"}";

    private static final String CUTS = "{\"configured\":true,\"presets\":[" +
            "{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\",\"request_id\":\"cut1\",\"cut\":" + CUT + "}," +
            "{\"id\":\"cut-answer\",\"label\":\"Just the answer\",\"state\":\"building\"}," +
            "{\"id\":\"cut-demo\",\"label\":\"Only the demo\",\"state\":\"failed\",\"error\":\"the model service is busy\"}" +
            "]}";

    private static final String CUTS_WITH_CHOICE = "{\"configured\":true,\"presets\":[" +
            "{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\",\"cut\":" + CUT + "}," +
            "{\"id\":\"cut-demo\",\"label\":\"Only the demo\",\"state\":\"ready\",\"cut\":" + CUT + "}]," +
            "\"selection\":{\"source\":\"chosen\",\"preset_id\":\"cut-demo\",\"state\":\"ready\",\"cut\":" + CUT + "}}";

    private static final String REQUEST = "{\"id\":\"cut1\",\"video_id\":\"abcdefghijk\",\"state\":\"ready\",\"source\":\"Living room TV\"," +
            "\"preset_id\":\"cut-no-filler\",\"prompt\":null,\"error\":null,\"created_at\":\"2026-11-20T10:00:00Z\"," +
            "\"updated_at\":\"2026-11-20T10:01:00Z\",\"title\":\"A video\",\"channel\":\"A channel\",\"duration_s\":240," +
            "\"stage\":null,\"cut\":" + CUT + "}";

    @Test
    public void aCutWithAnOptionalSourceOrTransitionsParsesAsToday() throws Exception {
        String cut = CUT
                .replace("\"source\":\"youtube_captions\"",
                        "\"source\":{\"kind\":\"imdb\",\"key\":\"imdb:tt0123456:s01e03\",\"release_duration_ms\":240000}")
                .replace("\"preset_id\":\"cut-no-filler\"",
                        "\"preset_id\":\"cut-no-filler\",\"transitions\":"
                                + "[{\"after_part\":0,\"type\":\"fade\",\"duration_ms\":500,"
                                + "\"asset\":{\"ref\":\"a\"},\"engine\":\"e\",\"engine_version\":\"1\",\"status\":\"ready\"}]");
        String cuts = "{\"configured\":true,\"presets\":[{\"id\":\"cut-no-filler\","
                + "\"label\":\"No filler\",\"state\":\"ready\",\"cut\":" + cut + "}]}";

        CutList parsed = UtubotParser.parseCuts(cuts);

        assertEquals(240_000, parsed.presets.get(0).cut.durationMs);
        assertEquals(2, parsed.presets.get(0).cut.parts.size());
        assertTrue(parsed.presets.get(0).isReady());
    }

    @Test
    public void parsesThePresetsOfAVideo() throws Exception {
        CutList cuts = UtubotParser.parseCuts(CUTS);

        assertTrue(cuts.configured);
        assertEquals(3, cuts.presets.size());

        assertEquals("cut-no-filler", cuts.presets.get(0).id);
        assertEquals("No filler", cuts.presets.get(0).label);
        assertEquals("ready", cuts.presets.get(0).state);
        assertEquals("cut1", cuts.presets.get(0).requestId);
        assertEquals(240_000, cuts.presets.get(0).cut.durationMs);
        assertEquals(1, cuts.presets.get(0).cut.skipRangesMs.size());
        assertEquals(60_000, cuts.presets.get(0).cut.skipRangesMs.get(0)[0]);
        assertEquals(108_000, cuts.presets.get(0).cut.skipRangesMs.get(0)[1]);
        assertEquals(192_000, cuts.presets.get(0).cut.keptMs);
        assertEquals("fast", cuts.presets.get(0).cut.model);

        assertEquals("building", cuts.presets.get(1).state);
        assertNull(cuts.presets.get(1).cut);
        assertEquals("failed", cuts.presets.get(2).state);
        assertEquals("the model service is busy", cuts.presets.get(2).error);
    }

    @Test
    public void aFailedPresetCanBeAskedAgainButAPendingOneCannot() throws Exception {
        CutList cuts = UtubotParser.parseCuts(CUTS);

        assertFalse(cuts.presets.get(0).canRequest()); // ready: apply or take off
        assertFalse(cuts.presets.get(1).canRequest()); // building
        assertTrue(cuts.presets.get(2).canRequest()); // failed: Retry starts a fresh request
    }

    @Test
    public void parsesARequestDocument() throws Exception {
        CutRequest request = UtubotParser.parseCutRequest(REQUEST);

        assertEquals("cut1", request.id);
        assertEquals("abcdefghijk", request.videoId);
        assertTrue(request.isReady());
        assertEquals("Living room TV", request.source);
        assertEquals("cut-no-filler", request.presetId);
        assertEquals("A video", request.title);
        assertEquals("A channel", request.channel);
        assertEquals(240, request.durationSec);
        assertEquals("No filler", request.cut.label);
        assertEquals(2, request.cut.parts.size());
        assertEquals("End", request.cut.parts.get(1).label);
        assertEquals(108_000, request.cut.parts.get(1).startMs);
    }

    @Test
    public void parsesACutDocumentWithASourceObjectTransitionsAndMode() throws Exception {
        CutList cuts = UtubotParser.parseCuts(CUTS.replace(CUT, NEW_CUT));

        Cut cut = cuts.presets.get(0).cut;
        assertEquals(240_000, cut.durationMs);
        assertEquals(1, cut.skipRangesMs.size());
        assertEquals(60_000, cut.skipRangesMs.get(0)[0]);
        assertEquals(108_000, cut.skipRangesMs.get(0)[1]);
        assertEquals(192_000, cut.keptMs);
        assertEquals("fast", cut.model);
        assertEquals(2, cut.parts.size());
        assertEquals("End", cut.parts.get(1).label);
        assertEquals(108_000, cut.parts.get(1).startMs);

        CutRequest request = UtubotParser.parseCutRequest(REQUEST.replace(CUT, NEW_CUT));
        assertTrue(request.isReady());
        assertEquals("No filler", request.cut.label);
        assertEquals(1, request.cut.skipRangesMs.size());
    }

    @Test
    public void aWaitingRequestIsPendingAndAFailedOneIsDone() throws Exception {
        assertTrue(UtubotParser.parseCutRequest(REQUEST.replace("ready", "waiting")).isWaiting());
        assertTrue(UtubotParser.parseCutRequest(REQUEST.replace("ready", "building")).isBuilding());
        assertTrue(UtubotParser.parseCutRequest(REQUEST.replace("ready", "needs_transcript")).isBuilding());
        assertTrue(UtubotParser.parseCutRequest(REQUEST.replace("\"state\":\"ready\"", "\"state\":\"failed\"")).isDone());
        assertTrue(UtubotParser.parseCutRequest(REQUEST).isDone());
    }

    @Test
    public void aRequestWithoutACutIsNotReady() throws Exception {
        assertFalse(UtubotParser.parseCutRequest(REQUEST.replace("\"cut\":" + CUT, "\"cut\":null")).isReady());
    }

    @Test
    public void parsesTheModesAndTheWatchedStateOfAPreset() throws Exception {
        String watchedCut = CUT.replace("\"model\":\"fast\"",
                "\"model\":\"fast\",\"mode\":\"watched\",\"watched\":{\"grids\":24,\"model\":\"qwen-vision\",\"partial\":false,\"coarse\":false}");
        String cuts = "{\"configured\":true,\"default_mode\":\"quick\",\"modes\":[" +
                "{\"id\":\"quick\",\"label\":\"Quick\",\"default\":true,\"available\":true}," +
                "{\"id\":\"watched\",\"label\":\"Watched \u00b7 about 12 min\",\"default\":false," +
                "\"available\":true,\"eta_s\":720}],\"presets\":[" +
                "{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"none\"," +
                "\"by_mode\":{\"quick\":{\"state\":\"ready\",\"cut\":" + CUT + "}," +
                "\"watched\":{\"state\":\"building\",\"request_id\":\"cut2\"}}}," +
                "{\"id\":\"cut-demo\",\"label\":\"Only the demo\",\"state\":\"failed\"," +
                "\"by_mode\":{\"quick\":{\"state\":\"none\"}," +
                "\"watched\":{\"state\":\"failed\",\"error\":\"the engine is in use\"}}}," +
                "{\"id\":\"cut-answer\",\"label\":\"Just the answer\",\"state\":\"ready\",\"cut\":" +
                watchedCut + "}]}";

        CutList parsed = UtubotParser.parseCuts(cuts);

        assertEquals("quick", parsed.defaultMode);
        assertEquals(2, parsed.modes.size());
        assertEquals("watched", parsed.modes.get(1).id);
        assertEquals(720, parsed.modes.get(1).etaSec);
        assertTrue(parsed.modes.get(0).defaultMode);

        CutPreset preset = parsed.presets.get(0);
        assertTrue(preset.forMode(CutMode.QUICK).isReady());
        assertEquals("cut2", preset.forMode(CutMode.WATCHED).requestId);
        assertEquals("the engine is in use", parsed.presets.get(1).forMode(CutMode.WATCHED).error);

        Cut watched = parsed.presets.get(2).cut;
        assertEquals(CutMode.WATCHED, watched.mode);
        assertEquals(24, watched.watched.grids);
        assertEquals("qwen-vision", watched.watched.model);
        assertFalse(watched.watched.partial);
    }

    @Test
    public void aWatchedRequestCarriesItsModeAndEstimate() throws Exception {
        CutRequest request = UtubotParser.parseCutRequest(REQUEST
                .replace("\"state\":\"ready\"", "\"state\":\"building\",\"mode\":\"watched\",\"eta_s\":120")
                .replace("\"stage\":null", "\"stage\":\"describing\""));

        assertEquals(CutMode.WATCHED, request.mode);
        assertEquals(120, request.etaSec);
        assertEquals("describing", request.stage);
    }

    @Test
    public void theMeFeaturesCarryCuts() throws Exception {
        Me me = UtubotParser.parseMe("{\"user\":\"owner\",\"features\":{\"assess\":true,\"cuts\":true}}");

        assertTrue(me.cuts);
        assertFalse(UtubotParser.parseMe("{\"user\":\"owner\",\"features\":{}}").cuts);
    }

    @Test
    public void parsesTheCutTheVideoOpensWith() throws Exception {
        CutList cuts = UtubotParser.parseCuts(CUTS_WITH_CHOICE);

        assertNotNull(cuts.selection);
        assertEquals("chosen", cuts.selection.source);
        assertEquals("cut-demo", cuts.selection.presetId);
        assertFalse(cuts.selection.off);
        assertTrue(cuts.selection.isReady());
        assertEquals("No filler", cuts.selection.cut.label);
    }

    @Test
    public void aMissingSelectionLeavesItNull() throws Exception {
        assertNull(UtubotParser.parseCuts(CUTS).selection);
        assertNull(UtubotParser.parseCuts("{}").selection);
    }

    @Test
    public void missingFieldsKeepTheirDefaults() throws Exception {
        CutList cuts = UtubotParser.parseCuts("{}");

        assertFalse(cuts.configured);
        assertTrue(cuts.presets.isEmpty());

        CutRequest request = UtubotParser.parseCutRequest("{\"id\":\"cut9\"}");

        assertEquals("cut9", request.id);
        assertNull(request.cut);
        assertEquals(UtubotModels.UNKNOWN, request.durationSec);
    }
}