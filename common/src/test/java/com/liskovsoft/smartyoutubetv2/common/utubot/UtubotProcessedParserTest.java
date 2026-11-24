package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;

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
public class UtubotProcessedParserTest {
    private static final String ITEM = "{\"video_id\":\"dQw4w9WgXcQ\",\"title\":\"A video\"," +
            "\"thumbnail\":\"https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg\",\"updated_at\":1763900000.0,\"summary\":true," +
            "\"captions\":[{\"job_id\":\"job1\",\"lang\":\"en\",\"translate_to\":\"de\",\"state\":\"ready\",\"progress\":1.0," +
            "\"error\":null,\"created_at\":1763899900.0,\"updated_at\":1763900000.0}," +
            "{\"job_id\":\"job2\",\"lang\":\"tr\",\"translate_to\":null,\"state\":\"processing\",\"progress\":0.5," +
            "\"error\":null,\"created_at\":1763899800.0,\"updated_at\":1763899900.0}]," +
            "\"cuts\":[{\"request_id\":\"cut1\",\"state\":\"ready\",\"preset_id\":\"cut-demo\",\"preset_label\":\"Only the demo\"," +
            "\"prompt\":null,\"error\":null,\"created_at\":1763899700.0,\"updated_at\":1763899800.0}," +
            "{\"request_id\":\"cut2\",\"state\":\"failed\",\"preset_id\":null,\"preset_label\":null," +
            "\"prompt\":\"Keep the demo\",\"error\":\"the model service is busy\",\"created_at\":1763899600.0,\"updated_at\":1763899700.0}]}";

    private static final String SECOND = "{\"video_id\":\"abcdefghijk\",\"title\":null,\"summary\":false," +
            "\"thumbnail\":\"https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg\",\"updated_at\":1763899000.0," +
            "\"captions\":[{\"job_id\":\"job3\",\"lang\":\"en\",\"translate_to\":null,\"state\":\"waiting\",\"progress\":0.0," +
            "\"error\":null,\"created_at\":1763898800.0,\"updated_at\":1763899000.0}]," +
            "\"cuts\":[]}";

    private static final String PROCESSED = "{\"videos\":[" + ITEM + "," + SECOND + "]}";

    @Test
    public void parsesTheRecentlyProcessedVideos() throws Exception {
        ProcessedList list = UtubotParser.parseProcessed(PROCESSED);

        assertEquals(2, list.videos.size());

        ProcessedItem first = list.videos.get(0);
        assertEquals("dQw4w9WgXcQ", first.videoId);
        assertEquals("A video", first.title);
        assertEquals("https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", first.thumbnail);
        assertEquals(1763900000.0, first.updatedAt, 0.0);
        assertTrue(first.summary);

        assertEquals(2, first.captions.size());
        assertEquals("job1", first.captions.get(0).jobId);
        assertEquals("en", first.captions.get(0).lang);
        assertEquals("de", first.captions.get(0).translateTo);
        assertEquals("ready", first.captions.get(0).state);
        assertEquals(1.0, first.captions.get(0).progress, 0.0);
        assertNull(first.captions.get(0).error);
        assertEquals(1763899900.0, first.captions.get(0).createdAt, 0.0);
        assertEquals(1763900000.0, first.captions.get(0).updatedAt, 0.0);
        assertTrue(first.captions.get(0).isReady());

        assertEquals("job2", first.captions.get(1).jobId);
        assertEquals("processing", first.captions.get(1).state);
        assertEquals(0.5, first.captions.get(1).progress, 0.0);
        assertNull(first.captions.get(1).translateTo);

        assertEquals(2, first.cuts.size());
        assertEquals("cut1", first.cuts.get(0).requestId);
        assertEquals("ready", first.cuts.get(0).state);
        assertEquals("cut-demo", first.cuts.get(0).presetId);
        assertEquals("Only the demo", first.cuts.get(0).presetLabel);
        assertNull(first.cuts.get(0).prompt);
        assertEquals(1763899800.0, first.cuts.get(0).updatedAt, 0.0);
        assertTrue(first.cuts.get(0).isReady());

        assertEquals("cut2", first.cuts.get(1).requestId);
        assertEquals("failed", first.cuts.get(1).state);
        assertEquals("Keep the demo", first.cuts.get(1).prompt);
        assertEquals("the model service is busy", first.cuts.get(1).error);

        ProcessedItem second = list.videos.get(1);
        assertEquals("abcdefghijk", second.videoId);
        assertNull(second.title);
        assertFalse(second.summary);
        assertEquals("waiting", second.captions.get(0).state);
        assertTrue(second.cuts.isEmpty());
    }

    @Test
    public void anEmptyHistoryIsAnEmptyList() throws Exception {
        assertTrue(UtubotParser.parseProcessed("{\"videos\":[]}").videos.isEmpty());
        assertTrue(UtubotParser.parseProcessed("{}").videos.isEmpty());
    }

    @Test
    public void missingFieldsKeepTheirDefaults() throws Exception {
        ProcessedList list = UtubotParser.parseProcessed("{\"videos\":[{\"video_id\":\"a\"}]}");
        ProcessedItem item = list.videos.get(0);

        assertEquals("a", item.videoId);
        assertNull(item.title);
        assertNull(item.thumbnail);
        assertEquals(0.0, item.updatedAt, 0.0);
        assertFalse(item.summary);
        assertTrue(item.captions.isEmpty());
        assertTrue(item.cuts.isEmpty());
    }

    @Test
    public void entriesWithoutAnIdAreSkipped() throws Exception {
        ProcessedList list = UtubotParser.parseProcessed("{\"videos\":[{\"title\":\"no id\"}," +
                "{\"video_id\":\"a\",\"captions\":[{\"lang\":\"en\"},{\"job_id\":\"job1\"}]," +
                "\"cuts\":[{\"state\":\"ready\"},{\"request_id\":\"cut1\"}]}]}");

        assertEquals(1, list.videos.size());
        assertEquals(1, list.videos.get(0).captions.size());
        assertEquals("job1", list.videos.get(0).captions.get(0).jobId);
        assertEquals(1, list.videos.get(0).cuts.size());
        assertEquals("cut1", list.videos.get(0).cuts.get(0).requestId);
    }
}
