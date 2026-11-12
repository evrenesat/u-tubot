package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.lang.reflect.Proxy;
import java.util.HashMap;
import java.util.Map;

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

    /**
     * A card the way the service makes it: only what is given is known
     */
    private static MediaItem item(long durationMs, String title, String author) {
        Map<String, Object> answers = new HashMap<>();
        answers.put("getVideoId", "aaaaaaaaaaa");
        answers.put("getDurationMs", durationMs);
        answers.put("getTitle", title);
        answers.put("getAuthor", author);

        return (MediaItem) Proxy.newProxyInstance(MediaItem.class.getClassLoader(), new Class<?>[]{MediaItem.class}, (proxy, method, args) -> {
            if (answers.containsKey(method.getName())) {
                return answers.get(method.getName());
            }

            Class<?> type = method.getReturnType();

            if (type == boolean.class) {
                return false;
            }

            if (type == int.class) {
                return 0;
            }

            if (type == long.class) {
                return 0L;
            }

            return null;
        });
    }

    @Test
    public void aCardSendsItsTitleChannelAndLength() {
        VideoMeta meta = UtubotMeta.from(Video.from(item(754_000, "A title", "A channel")));

        assertEquals("aaaaaaaaaaa", meta.videoId);
        assertEquals("A title", meta.title);
        assertEquals("A channel", meta.channel);
        assertEquals(754, meta.durationSec);
    }

    @Test
    public void theLengthComesFromTheBadgeWhenTheCardHasNoDuration() {
        Video video = new Video();
        video.videoId = "aaaaaaaaaaa";
        video.badge = "1:02:03";

        assertEquals(3723, UtubotMeta.from(video).durationSec);
    }

    @Test
    public void aCopyOfACardKeepsItsLengthThroughTheMediaItem() {
        // Video.from(Video) copies the media item and the badge, not the duration field
        Video copy = Video.from(Video.from(item(600_000, "A title", "A channel")));

        assertEquals(-1, copy.getDurationMs());
        assertEquals(600, UtubotMeta.from(copy).durationSec);
    }

    @Test
    public void aVideoOfUnknownLengthSendsNone() {
        Video video = new Video();
        video.videoId = "aaaaaaaaaaa";
        video.title = "T";

        assertEquals(0, UtubotMeta.from(video).durationSec);
    }
}
