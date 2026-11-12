package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotMetaTest {
    @Test
    public void parsesClockBadges() {
        assertEquals(754, UtubotMeta.parseClock("12:34"));
        assertEquals(3723, UtubotMeta.parseClock("1:02:03"));
        assertEquals(0, UtubotMeta.parseClock("LIVE"));
        assertEquals(0, UtubotMeta.parseClock(null));
        assertEquals(0, UtubotMeta.parseClock("a:b"));
    }

    @Test
    public void readsViewsAndPublishedFromTheSecondTitle() {
        VideoMeta meta = new VideoMeta();
        UtubotMeta.fillStats(meta, "Some Channel • 1.2M views • 3 days ago");

        assertEquals("1.2M views", meta.views);
        assertEquals("3 days ago", meta.published);
    }

    @Test
    public void leavesStatsEmptyWithoutViews() {
        VideoMeta meta = new VideoMeta();
        UtubotMeta.fillStats(meta, "Some Channel");
        UtubotMeta.fillStats(meta, null);

        assertNull(meta.views);
        assertNull(meta.published);
    }

    @Test
    public void metaJsonSkipsEmptyFields() throws Exception {
        VideoMeta meta = new VideoMeta();
        meta.videoId = "abc";
        meta.title = "T";
        meta.durationSec = 0;

        String json = meta.toJson().toString();

        assertTrue(json.contains("\"video_id\":\"abc\""));
        assertTrue(json.contains("\"title\":\"T\""));
        assertTrue(!json.contains("duration_s"));
        assertTrue(!json.contains("channel"));
    }
}
