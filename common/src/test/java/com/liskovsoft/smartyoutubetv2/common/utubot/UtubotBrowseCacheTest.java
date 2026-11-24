package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotBrowseCacheTest {
    private static final long MINUTE = 60_000;
    private static final String IDENTITY = "en_US|owner";
    private Activity mActivity;
    private File mRoot;

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mRoot = new File(mActivity.getFilesDir(), "utubot_browse_test");
        clear(mRoot);
    }

    @After
    public void tearDown() {
        clear(mRoot);
    }

    @Test
    public void contentShowsImmediatelyAndRefreshesOnlyAfterTheNamedMinutes() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();
        long loadedAt = 1_000_000;

        cache.save(section, Collections.singletonList(group(section, "Home", -1, "aaa")), IDENTITY, loadedAt);

        assertEquals(UtubotBrowseCache.State.FRESH, cache.state(section.getId(), IDENTITY, loadedAt + 5 * MINUTE - 1, 5));
        assertEquals(UtubotBrowseCache.State.STALE, cache.state(section.getId(), IDENTITY, loadedAt + 5 * MINUTE, 5));

        List<VideoGroup> groups = cache.groups(section, IDENTITY);

        assertNotNull(groups);
        assertEquals(1, groups.size());
        assertEquals("Home", groups.get(0).getTitle());
        assertEquals("aaa", groups.get(0).getVideos().get(0).videoId);
    }

    @Test
    public void theDiskCacheSurvivesAnAppRestart() {
        UtubotBrowseCache first = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();

        first.save(section, Collections.singletonList(group(section, "Home", -1, "aaa", "bbb")), IDENTITY, 1_000_000);

        UtubotBrowseCache restarted = new UtubotBrowseCache(mRoot);
        List<VideoGroup> groups = restarted.groups(section, IDENTITY);

        assertNotNull(groups);
        assertEquals(2, groups.get(0).getVideos().size());
        assertEquals("Video aaa", groups.get(0).getVideos().get(0).title);
        assertEquals("Video bbb", groups.get(0).getVideos().get(1).title);
    }

    @Test
    public void anotherLocaleOrAccountDoesNotReadTheCache() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();

        cache.save(section, Collections.singletonList(group(section, "Home", -1, "aaa")), IDENTITY, 1_000_000);

        assertNull(cache.groups(section, "tr_TR|owner"));
        assertNull(cache.groups(section, "en_US|partner"));
        assertEquals(UtubotBrowseCache.State.MISSING, cache.state(section.getId(), "tr_TR|owner", 1_000_000, 5));
        assertNotNull(cache.groups(section, IDENTITY));
    }

    @Test
    public void invalidationDropsTheMemoryAndTheDisk() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();
        File[] files;

        cache.save(section, Collections.singletonList(group(section, "Home", -1, "aaa")), IDENTITY, 1_000_000);

        files = mRoot.listFiles();
        assertNotNull(files);
        assertEquals(1, files.length);

        cache.invalidate();

        assertNull(cache.groups(section, IDENTITY));
        files = mRoot.listFiles();
        assertNotNull(files);
        assertEquals(0, files.length);
    }

    @Test
    public void aRefreshAttemptCountsAsTheLastLoad() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();
        long loadedAt = 1_000_000;

        cache.save(section, Collections.singletonList(group(section, "Home", -1, "aaa")), IDENTITY, loadedAt);
        cache.markAttempt(section.getId(), loadedAt + 4 * MINUTE);

        assertEquals(UtubotBrowseCache.State.FRESH, cache.state(section.getId(), IDENTITY, loadedAt + 4 * MINUTE + 1, 5));
        assertEquals(UtubotBrowseCache.State.STALE, cache.state(section.getId(), IDENTITY, loadedAt + 9 * MINUTE, 5));
    }

    @Test
    public void theRowFieldsTheCardsNeedAreKept() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();
        Video video = new Video();
        video.videoId = "aaa";
        video.title = "A title";
        video.secondTitle = "A channel • 3 days ago";
        video.author = "A channel";
        video.cardImageUrl = "https://example.invalid/aaa.jpg";
        video.altCardImageUrl = "https://example.invalid/aaa-alt.jpg";
        video.badge = "12:34";
        video.percentWatched = 42;
        video.isShorts = true;
        video.isLive = true;
        video.channelId = "UCaaa";
        video.utubotMark = "Clickbait";
        video.itemType = 1;
        VideoGroup group = VideoGroup.from(Collections.singletonList(video), section, -1);
        group.setId(123);
        group.setTitle("Home");

        cache.save(section, Collections.singletonList(group), IDENTITY, 1_000_000);

        VideoGroup restored = cache.groups(section, IDENTITY).get(0);
        Video restoredVideo = restored.getVideos().get(0);

        assertEquals(123, restored.getId());
        assertEquals("Home", restored.getTitle());
        assertEquals("A title", restoredVideo.title);
        assertEquals("A channel • 3 days ago", restoredVideo.secondTitle);
        assertEquals("A channel", restoredVideo.author);
        assertEquals("https://example.invalid/aaa.jpg", restoredVideo.cardImageUrl);
        assertEquals("https://example.invalid/aaa-alt.jpg", restoredVideo.altCardImageUrl);
        assertEquals("12:34", restoredVideo.badge);
        assertEquals(42, restoredVideo.percentWatched, 0.001);
        assertTrue(restoredVideo.isShorts);
        assertTrue(restoredVideo.isLive);
        assertEquals("UCaaa", restoredVideo.channelId);
        assertEquals("Clickbait", restoredVideo.utubotMark);
        assertEquals(1, restoredVideo.itemType);
    }

    @Test
    public void aNextPageKeepsTheRowAndAddsItsVideos() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();
        VideoGroup first = group(section, "Home", -1, "aaa");
        long loadedAt = 1_000_000;

        cache.save(section, Collections.singletonList(first), IDENTITY, loadedAt);

        Video aaa = first.getVideos().get(0);
        Video bbb = video("bbb");
        List<Video> videos = new ArrayList<>(first.getVideos());
        videos.add(bbb);
        VideoGroup page = VideoGroup.from(videos, section, -1);
        page.setId(first.getId());
        page.setTitle(first.getTitle());

        cache.append(section, page, IDENTITY, loadedAt + MINUTE);

        List<VideoGroup> groups = cache.groups(section, IDENTITY);

        assertEquals(1, groups.size());
        assertEquals(2, groups.get(0).getVideos().size());
        assertEquals("aaa", groups.get(0).getVideos().get(0).videoId);
        assertEquals("bbb", groups.get(0).getVideos().get(1).videoId);
        assertEquals(UtubotBrowseCache.State.FRESH, cache.state(section.getId(), IDENTITY, loadedAt + MINUTE + 1, 5));
        assertEquals("aaa", aaa.videoId);
    }

    @Test
    public void anOldRowIsFoundByItsTitleAndPosition() {
        BrowseSection section = section();
        VideoGroup oldFirst = group(section, "Home", 0, "aaa");
        VideoGroup oldSecond = group(section, "Subscriptions", 1, "bbb");
        List<VideoGroup> oldGroups = new ArrayList<>();

        oldGroups.add(oldFirst);
        oldGroups.add(oldSecond);

        assertEquals(oldSecond.getId(), UtubotBrowseCache.findOldId(oldGroups, group(section, "Subscriptions", 1, "ccc")));
        assertEquals(-1, UtubotBrowseCache.findOldId(oldGroups, group(section, "Watch later", 2, "ccc")));
    }

    @Test
    public void aMultiGridColumnReplacesOnlyItsPosition() {
        BrowseSection section = new BrowseSection(MediaGroup.TYPE_CHANNEL_UPLOADS, "Channels", BrowseSection.TYPE_MULTI_GRID, 0);
        VideoGroup column0 = group(section, "Channels", 0, "aaa");
        VideoGroup column1 = group(section, "Channels", 1, "bbb");
        List<VideoGroup> merged = UtubotBrowseCache.mergeByPosition(Collections.singletonList(column0), column1);

        assertEquals(2, merged.size());
        assertEquals(0, merged.get(0).getPosition());
        assertEquals(1, merged.get(1).getPosition());

        VideoGroup newColumn0 = group(section, "Channels", 0, "ccc");
        merged = UtubotBrowseCache.mergeByPosition(merged, newColumn0);

        assertEquals(2, merged.size());
        assertEquals("ccc", merged.get(0).getVideos().get(0).videoId);
        assertEquals("bbb", merged.get(1).getVideos().get(0).videoId);
    }

    @Test
    public void eachSectionKeepsItsOwnRefreshClock() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection home = section();
        BrowseSection subscriptions = new BrowseSection(MediaGroup.TYPE_SUBSCRIPTIONS, "Subscriptions", BrowseSection.TYPE_GRID, 0);
        long now = 1_000_000;

        cache.save(home, Collections.singletonList(group(home, "Home", -1, "aaa")), IDENTITY, now);
        cache.save(subscriptions, Collections.singletonList(group(subscriptions, "Subscriptions", -1, "bbb")), IDENTITY, now - 20 * MINUTE);
        cache.markAttempt(home.getId(), now + MINUTE);

        assertEquals(UtubotBrowseCache.State.FRESH, cache.state(home.getId(), IDENTITY, now + 6 * MINUTE, 10));
        assertEquals(UtubotBrowseCache.State.STALE, cache.state(subscriptions.getId(), IDENTITY, now + 6 * MINUTE, 10));
    }

    @Test
    public void anEntryAboveTheCapIsDiscarded() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();
        List<Video> videos = new ArrayList<>();

        for (int i = 0; i < 150; i++) {
            Video video = video("v" + i);
            video.description = text(4_096);
            videos.add(video);
        }

        VideoGroup group = VideoGroup.from(videos, section, -1);
        group.setId(1_000);
        group.setTitle("Home");

        cache.save(section, Collections.singletonList(group), IDENTITY, 1_000_000);

        assertNull(cache.groups(section, IDENTITY));
        assertEquals(0, cache.count());
        assertFalse(new File(mRoot, section.getId() + ".json").exists());
    }

    /**
     * The cards of the cache come without the page key of their row: scrolling past them waits for the background refresh.
     */
    @Test
    public void cachedGroupsHaveNoPageToContinue() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();

        cache.save(section, Collections.singletonList(group(section, "Home", -1, "aaa", "bbb")), IDENTITY, 1_000_000);

        VideoGroup restored = cache.groups(section, IDENTITY).get(0);

        assertNull(restored.getMediaGroup());
        assertNull(restored.getNextPageKey());
    }

    @Test
    public void theCacheIsEmptyBeforeAnythingWasLoaded() {
        UtubotBrowseCache cache = new UtubotBrowseCache(mRoot);
        BrowseSection section = section();

        assertEquals(UtubotBrowseCache.State.MISSING, cache.state(section.getId(), IDENTITY, 1_000_000, 5));
        assertNull(cache.groups(section, IDENTITY));
        assertEquals(0, cache.count());
        assertFalse(new File(mRoot, section.getId() + ".json").exists());
    }

    private static BrowseSection section() {
        return new BrowseSection(MediaGroup.TYPE_HOME, "Home", BrowseSection.TYPE_ROW, 0);
    }

    private static VideoGroup group(BrowseSection section, String title, int position, String... videoIds) {
        List<Video> videos = new ArrayList<>();

        for (String videoId : videoIds) {
            videos.add(video(videoId));
        }

        VideoGroup group = VideoGroup.from(videos, section, position);
        group.setId(1_000 + position);
        group.setTitle(title);

        return group;
    }

    private static Video video(String videoId) {
        Video video = new Video();
        video.videoId = videoId;
        video.title = "Video " + videoId;
        video.author = "Channel " + videoId;
        video.badge = "1:00";

        return video;
    }

    private static String text(int length) {
        StringBuilder text = new StringBuilder(length);

        for (int i = 0; i < length; i++) {
            text.append((char) ('a' + i % 26));
        }

        return text.toString();
    }

    private static void clear(File root) {
        File[] files = root.listFiles();

        if (files != null) {
            for (File file : files) {
                assertTrue(file.delete());
            }
        }

        assertTrue(root.exists() || root.mkdirs());
    }
}
