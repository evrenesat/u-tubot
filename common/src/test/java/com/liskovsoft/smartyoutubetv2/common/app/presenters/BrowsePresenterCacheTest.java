package com.liskovsoft.smartyoutubetv2.common.app.presenters;

import android.app.Activity;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.ErrorFragmentData;
import com.liskovsoft.smartyoutubetv2.common.app.views.BrowseView;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotBrowseCache;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import io.reactivex.Observable;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * The presenter's side of the browse cache, with a fake view and no YouTube: cached replay, in-place reuse of the row ids,
 * a multi-part refresh, stale rows taken out only after every part, and a failed part that keeps the cached cards.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class BrowsePresenterCacheTest {
    private static final long MINUTE = 60_000;
    private static final String LIKED_MUSIC = "Liked music";
    private static final String MUSIC = "Music";
    private FakeBrowseView mView;
    private BrowsePresenter mPresenter;
    private UtubotBrowseCache mCache;

    @Before
    public void setUp() {
        BrowsePresenter.unhold();
        mView = Robolectric.buildActivity(FakeBrowseView.class).setup().get();
        mPresenter = BrowsePresenter.instance(mView);
        mPresenter.setView(mView);
        mPresenter.onViewInitialized();
        mCache = UtubotBrowseCache.instance(mView);
        mCache.invalidate();
    }

    @After
    public void tearDown() {
        mCache.invalidate();
        BrowsePresenter.unhold();
    }

    @Test
    public void freshCacheReplaysItsCardsWithoutALoad() throws Exception {
        BrowseSection section = musicSection();
        AtomicInteger subscriptions = new AtomicInteger();
        List<MediaGroup> first = Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new-one"));
        List<MediaGroup> second = Collections.singletonList(mediaGroup(MUSIC, 6, "new-two"));

        seed(section, cachedGroups(section, group(section, LIKED_MUSIC, 0, 7_000, "old-one"),
                group(section, MUSIC, 1, 8_000, "old-two")), now(), false);
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, Observable.defer(() -> {
            subscriptions.incrementAndGet();
            return Observable.just(first, second);
        }));

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);

        assertEquals(0, subscriptions.get());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(7_000, LIKED_MUSIC, 1));
        assertTrue(mView.hasGroup(8_000, MUSIC, 1));
    }

    @Test
    public void multiPartRefreshSavesEveryPartAndTakesStaleRowsOutOnce() throws Exception {
        BrowseSection section = musicSection();
        List<MediaGroup> first = Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new-one"));
        List<MediaGroup> second = Collections.singletonList(mediaGroup(MUSIC, 6, "new-two"));

        seed(section, cachedGroups(section, group(section, LIKED_MUSIC, 0, 7_000, "old-one"),
                group(section, MUSIC, 1, 8_000, "old-two")), now() - 20 * MINUTE, true);
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, Observable.just(first, second));

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);

        List<VideoGroup> cached = mCache.groups(section, identity());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(7_000, LIKED_MUSIC, 1));
        assertTrue(mView.hasGroup(8_000, MUSIC, 1));
        assertNotNull(cached);
        assertEquals(2, cached.size());
        assertEquals(1, cached.get(0).getVideos().size());
        assertEquals(1, cached.get(1).getVideos().size());
        assertEquals(MUSIC, cached.get(1).getTitle());
        assertEquals(0, mView.emptyUpdates());
    }

    @Test
    public void aFailedLaterPartKeepsTheCachedCardsAndTheLastWholeCache() throws Exception {
        BrowseSection section = musicSection();
        List<MediaGroup> first = Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new-one"));
        List<VideoGroup> cachedBefore = cachedGroups(section, group(section, LIKED_MUSIC, 0, 7_000, "old-one"),
                group(section, MUSIC, 1, 8_000, "old-two"));

        seed(section, cachedBefore, now() - 20 * MINUTE, true);
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC,
                Observable.concat(Observable.just(first), Observable.error(new RuntimeException("the later part failed"))));

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);

        List<VideoGroup> cached = mCache.groups(section, identity());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(7_000, LIKED_MUSIC, 1));
        assertTrue(mView.hasGroup(8_000, MUSIC, 1));
        assertNotNull(cached);
        assertEquals(2, cached.size());
        assertEquals(LIKED_MUSIC, cached.get(0).getTitle());
        assertEquals(MUSIC, cached.get(1).getTitle());
        // The first part's cache save, which used to empty the cached card of the second part, is gone; so is its stale row.
        assertEquals(0, mView.emptyUpdates());
    }

    @Test
    public void accountChangeInvalidatesTheCacheThroughThePresenter() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 7_000, "old-one")), now(), false);

        assertNotNull(mCache.groups(section, identity()));

        mPresenter.onAccountChanged(null);

        assertEquals(0, mCache.count());
        assertEquals(null, mCache.groups(section, identity()));
    }

    private BrowseSection musicSection() throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField("mSections");
        field.setAccessible(true);
        List<BrowseSection> sections = (List<BrowseSection>) field.get(mPresenter);

        for (BrowseSection section : sections) {
            if (section.getId() == MediaGroup.TYPE_MUSIC) {
                return section;
            }
        }

        throw new IllegalStateException("Music isn't in the sections");
    }

    private void seed(BrowseSection section, List<VideoGroup> groups, long loadedAt, boolean stale) throws Exception {
        mCache.save(section, groups, identity(), loadedAt);
    }

    private String identity() throws Exception {
        Method method = BrowsePresenter.class.getDeclaredMethod("getBrowseCacheIdentity");
        method.setAccessible(true);

        return (String) method.invoke(mPresenter);
    }

    private void putMapping(String fieldName, int sectionId, Observable<?> observable) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        Map<Integer, Observable<?>> map = (Map<Integer, Observable<?>>) field.get(mPresenter);
        map.put(sectionId, observable);
    }

    private long now() {
        return System.currentTimeMillis();
    }

    private static List<VideoGroup> cachedGroups(BrowseSection section, VideoGroup... groups) {
        return new ArrayList<>(Arrays.asList(groups));
    }

    private static VideoGroup group(BrowseSection section, String title, int position, int id, String... videoIds) {
        List<Video> videos = new ArrayList<>();

        for (String videoId : videoIds) {
            Video video = new Video();
            video.videoId = videoId;
            video.title = "Video " + videoId;
            video.author = "Channel " + videoId;
            video.badge = "1:00";
            videos.add(video);
        }

        VideoGroup group = VideoGroup.from(videos, section, position);
        group.setId(id);
        group.setTitle(title);

        return group;
    }

    private static MediaGroup mediaGroup(String title, int count, String videoPrefix) {
        List<MediaItem> items = new ArrayList<>();

        for (int i = 0; i < count; i++) {
            items.add(mediaItem(i, title + " " + i, videoPrefix + i));
        }

        return (MediaGroup) Proxy.newProxyInstance(MediaGroup.class.getClassLoader(), new Class[]{MediaGroup.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "getType":
                            return MediaGroup.TYPE_MUSIC;
                        case "getTitle":
                            return title;
                        case "getMediaItems":
                            return items;
                        case "isEmpty":
                            return items.isEmpty();
                        case "getFilteredVideoCount":
                            return 0;
                        case "getRowKind":
                            return MediaGroup.ROW_KIND_NONE;
                        case "getTopic":
                            return MediaGroup.TOPIC_NONE;
                        case "isChannelRow":
                        case "isSearchTopicRow":
                            return false;
                        case "hashCode":
                            return title.hashCode();
                        case "equals":
                            return proxy == args[0];
                        case "toString":
                            return "MediaGroup " + title;
                        default:
                            return defaultValue(method.getReturnType());
                    }
                });
    }

    private static MediaItem mediaItem(int id, String title, String videoId) {
        return (MediaItem) Proxy.newProxyInstance(MediaItem.class.getClassLoader(), new Class[]{MediaItem.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "getId":
                            return id;
                        case "getTitle":
                            return title;
                        case "getVideoId":
                            return videoId;
                        // A live video: no playback warm-up, which is a YouTube request
                        case "isLive":
                            return true;
                        case "getType":
                            return MediaItem.TYPE_VIDEO;
                        case "getAuthor":
                            return "Channel";
                        case "getBadgeText":
                            return "1:00";
                        case "hashCode":
                            return id;
                        case "equals":
                            return proxy == args[0];
                        case "toString":
                            return "MediaItem " + title;
                        default:
                            return defaultValue(method.getReturnType());
                    }
                });
    }

    private static Object defaultValue(Class<?> type) {
        if (type == boolean.class) {
            return false;
        }
        if (type == int.class) {
            return 0;
        }
        if (type == long.class) {
            return 0L;
        }
        if (type == float.class) {
            return 0f;
        }
        if (type == double.class) {
            return 0d;
        }

        return null;
    }

    public static class FakeBrowseView extends Activity implements BrowseView {
        private final List<VideoGroup> mUpdates = new ArrayList<>();
        private final List<Video> mSelectedItems = new ArrayList<>();
        private boolean mProgressShowing;
        private int errors;

        @Override
        public void addSection(int index, BrowseSection section) {
        }

        @Override
        public void removeSection(BrowseSection category) {
        }

        @Override
        public void removeAllSections() {
        }

        @Override
        public void selectSection(int index, boolean focusOnContent) {
        }

        @Override
        public void updateSection(VideoGroup group) {
            mUpdates.add(group);
        }

        @Override
        public void updateSection(SettingsGroup group) {
        }

        @Override
        public void clearSection(BrowseSection section) {
        }

        @Override
        public void selectSectionItem(int index) {
        }

        @Override
        public void selectSectionItem(Video item) {
            mSelectedItems.add(item);
        }

        @Override
        public void showError(ErrorFragmentData data) {
            errors++;
        }

        @Override
        public void showProgressBar(boolean show) {
            mProgressShowing = show;
        }

        @Override
        public boolean isProgressBarShowing() {
            return mProgressShowing;
        }

        @Override
        public void focusOnContent() {
        }

        @Override
        public boolean isEmpty() {
            return mUpdates.isEmpty();
        }

        @Override
        public void updateBadge() {
        }

        private boolean hasGroup(int id, String title, int size) {
            for (VideoGroup group : mUpdates) {
                if (group.getId() == id && title.equals(group.getTitle()) && group.getVideos().size() == size) {
                    return true;
                }
            }

            return false;
        }

        /**
         * A row replaced by an empty one: a cached row cleared before its part arrived
         */
        private int emptyUpdates() {
            int count = 0;

            for (VideoGroup group : mUpdates) {
                if (group.isEmpty()) {
                    count++;
                }
            }

            return count;
        }
    }
}
