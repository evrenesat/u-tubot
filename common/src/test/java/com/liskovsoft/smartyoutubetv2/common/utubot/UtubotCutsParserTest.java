package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
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

    private static final String CUTS = "{\"configured\":true,\"default_mode\":\"watched\",\"mode_rule\":\"channel\"," +
            "\"channel_id\":\"UCabc\",\"channel_name\":\"A channel\",\"channel_mode\":\"watched\",\"presets\":[" +
            "{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\",\"request_id\":\"cut1\",\"cut\":" + CUT + "}," +
            "{\"id\":\"cut-answer\",\"label\":\"Just the answer\",\"state\":\"building\"}," +
            "{\"id\":\"cut-demo\",\"label\":\"Only the demo\",\"state\":\"failed\",\"error\":\"the model service is busy\"}" +
            "]}";

    private static final String REQUEST = "{\"id\":\"cut1\",\"video_id\":\"abcdefghijk\",\"state\":\"ready\",\"source\":\"Living room TV\"," +
            "\"mode\":\"watched\",\"mode_rule\":\"channel\",\"channel_id\":\"UCabc\",\"preset_id\":\"cut-no-filler\",\"prompt\":null,\"error\":null,\"created_at\":\"2026-11-20T10:00:00Z\"," +
            "\"updated_at\":\"2026-11-20T10:01:00Z\",\"title\":\"A video\",\"channel\":\"A channel\",\"duration_s\":240," +
            "\"stage\":null,\"cut\":" + CUT + "}";

    @Test
    public void parsesThePresetsOfAVideo() throws Exception {
        CutList cuts = UtubotParser.parseCuts(CUTS);

        assertTrue(cuts.configured);
        assertEquals("watched", cuts.defaultMode);
        assertEquals("channel", cuts.modeRule);
        assertEquals("UCabc", cuts.channelId);
        assertEquals("A channel", cuts.channelName);
        assertEquals("watched", cuts.channelMode);
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
        assertEquals("watched", request.mode);
        assertEquals("channel", request.modeRule);
        assertEquals("UCabc", request.channelId);
        assertEquals(240, request.durationSec);
        assertEquals("No filler", request.cut.label);
        assertEquals(2, request.cut.parts.size());
        assertEquals("End", request.cut.parts.get(1).label);
        assertEquals(108_000, request.cut.parts.get(1).startMs);
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
    public void theMeFeaturesCarryCuts() throws Exception {
        Me me = UtubotParser.parseMe("{\"user\":\"owner\",\"features\":{\"assess\":true,\"cuts\":true}}");

        assertTrue(me.cuts);
        assertFalse(UtubotParser.parseMe("{\"user\":\"owner\",\"features\":{}}").cuts);
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