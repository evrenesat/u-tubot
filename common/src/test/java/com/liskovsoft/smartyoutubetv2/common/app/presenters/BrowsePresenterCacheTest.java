package com.liskovsoft.smartyoutubetv2.common.app.presenters;

import android.app.Activity;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.ErrorFragmentData;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.BrowseView;
import com.liskovsoft.smartyoutubetv2.common.prefs.AiSListFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.CollaborationsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HomeRowsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.prefs.WatchLaterData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotBrowseCache;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.youtubeapi.service.internal.MediaServiceData;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;

import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;

import io.reactivex.Observable;
import io.reactivex.subjects.PublishSubject;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The presenter's side of the browse cache, with a fake view and no YouTube: cached replay, in-place reuse of the row ids,
 * a multi-part refresh, stale rows taken out only after every part, a failed part that keeps the cached cards, the channel
 * uploads multi-grid's cached columns, a completed refresh with no view or cached rows, and cards removed from the cache.
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
    private FakeChannelUploadsPresenter mUploadsPresenter;

    @Before
    public void setUp() throws Exception {
        BrowsePresenter.unhold();
        mView = Robolectric.buildActivity(FakeBrowseView.class).setup().get();
        resetHoldingSettings();
        mPresenter = BrowsePresenter.instance(mView);
        mPresenter.setView(mView);
        mPresenter.onViewInitialized();
        mCache = UtubotBrowseCache.instance(mView);
        mCache.invalidate();
        mUploadsPresenter = new FakeChannelUploadsPresenter(mView);
        setChannelUploadsPresenter(mUploadsPresenter);
    }

    @After
    public void tearDown() throws Exception {
        mCache.invalidate();
        setChannelUploadsPresenter(null);
        BrowsePresenter.unhold();
    }

    @Test
    public void freshChannelUploadsCacheReplaysBothColumnsWithoutLoadingTheUploads() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        MainUIData.instance(mView).setUploadsAutoLoadEnabled(true);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        assertEquals(BrowseSection.TYPE_MULTI_GRID, section.getType());
        VideoGroup channels = channelGroup(section, "Channels", 0, 7_100, "channel-one", "channel-two");
        VideoGroup uploads = group(section, "Uploads", 1, 7_200, "upload-one", "upload-two");

        seed(section, cachedGroups(section, channels, uploads), now(), false);
        AtomicInteger channelLoads = new AtomicInteger();
        putMapping("mGridMapping", MediaGroup.TYPE_CHANNEL_UPLOADS, Observable.defer(() -> {
            channelLoads.incrementAndGet();
            return Observable.just(mediaGroup("Channels", 2, "channel", MediaGroup.TYPE_CHANNEL_UPLOADS));
        }));
        mUploadsPresenter.setError(new RuntimeException("no uploads request on a fresh cache"));

        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        // The replayed channels make the view auto-select its first channel (see ModernChannelsView)
        mPresenter.onVideoItemSelected(channels.getVideos().get(0));

        assertEquals(0, channelLoads.get());
        assertEquals(0, mUploadsPresenter.calls());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(7_100, "Channels", 2));
        assertTrue(mView.hasGroup(7_200, "Uploads", 2));
    }

    @Test
    public void failedUploadsRefreshShowsTheCachedUploadsColumnAgain() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        MainUIData.instance(mView).setUploadsAutoLoadEnabled(true);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        VideoGroup cachedChannels = channelGroup(section, "Channels", 0, 8_100, "old-channel");
        VideoGroup cachedUploads = group(section, "Uploads", 1, 8_200, "old-upload-one", "old-upload-two");

        seed(section, cachedGroups(section, cachedChannels, cachedUploads), now() - 20 * MINUTE, true);
        putMapping("mGridMapping", MediaGroup.TYPE_CHANNEL_UPLOADS,
                Observable.just(mediaGroup("Channels", 4, "new-channel", MediaGroup.TYPE_CHANNEL_UPLOADS)));
        mUploadsPresenter.setError(new RuntimeException("the uploads refresh failed"));

        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        awaitGroup(8_100, "Channels", 4);
        // The refreshed channels make the view auto-select its first channel (see ModernChannelsView)
        mPresenter.onVideoItemSelected(cachedChannels.getVideos().get(0));

        assertEquals(1, mUploadsPresenter.calls());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(8_200, "Uploads", 2));
        List<VideoGroup> cached = mCache.groups(section, identity());
        assertNotNull(cached);
        assertEquals("Channels", cached.get(0).getTitle());
        assertEquals(4, cached.get(0).getVideos().size());
        assertEquals("Uploads", cached.get(1).getTitle());
        assertEquals(2, cached.get(1).getVideos().size());

        // The failed refresh isn't retried on the next focus within the window
        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        mPresenter.onVideoItemSelected(cachedChannels.getVideos().get(0));
        assertEquals(1, mUploadsPresenter.calls());
    }

    @Test
    public void selectingAnotherChannelOnAFreshCacheLoadsItsUploads() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        MainUIData.instance(mView).setUploadsAutoLoadEnabled(true);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        VideoGroup channels = channelGroup(section, "Channels", 0, 7_500, "channel-one", "channel-two");
        VideoGroup uploads = group(section, "Uploads", 1, 7_600, "upload-one", "upload-two");

        seed(section, cachedGroups(section, channels, uploads), now(), false);
        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        mPresenter.onVideoItemSelected(channels.getVideos().get(0));
        assertEquals(0, mUploadsPresenter.calls());

        mPresenter.onVideoItemSelected(channels.getVideos().get(1));

        assertEquals(1, mUploadsPresenter.calls());
    }

    @Test
    public void selectingAnotherChannelAfterAFailedChannelsRefreshLoadsItsUploads() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        MainUIData.instance(mView).setUploadsAutoLoadEnabled(true);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        VideoGroup channels = channelGroup(section, "Channels", 0, 7_700, "channel-one", "channel-two");
        VideoGroup uploads = group(section, "Uploads", 1, 7_800, "upload-one", "upload-two");

        seed(section, cachedGroups(section, channels, uploads), now() - 20 * MINUTE, true);
        putMapping("mGridMapping", MediaGroup.TYPE_CHANNEL_UPLOADS, Observable.error(new RuntimeException("the channels refresh failed")));

        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        ShadowLooper.idleMainLooper();
        mPresenter.onVideoItemSelected(channels.getVideos().get(1));

        assertEquals(1, mUploadsPresenter.calls());
        assertEquals(0, mView.errors);
    }

    @Test
    public void selectingAnotherChannelAfterAFailedUploadsRefreshLoadsItsUploads() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        MainUIData.instance(mView).setUploadsAutoLoadEnabled(true);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        VideoGroup channels = channelGroup(section, "Channels", 0, 7_900, "channel-one", "channel-two");
        VideoGroup uploads = group(section, "Uploads", 1, 7_950, "upload-one", "upload-two");

        seed(section, cachedGroups(section, channels, uploads), now() - 20 * MINUTE, true);
        putMapping("mGridMapping", MediaGroup.TYPE_CHANNEL_UPLOADS,
                Observable.just(mediaGroup("Channels", 4, "new-channel", MediaGroup.TYPE_CHANNEL_UPLOADS)));
        mUploadsPresenter.setError(new RuntimeException("the uploads refresh failed"));

        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        awaitGroup(7_900, "Channels", 4);
        mPresenter.onVideoItemSelected(channels.getVideos().get(0));
        mPresenter.onVideoItemSelected(channels.getVideos().get(1));

        assertEquals(2, mUploadsPresenter.calls());
    }

    @Test
    public void cachedRowsRefreshKeepsTheFocusedCard() throws Exception {
        BrowseSection section = musicSection();
        String target = "target0";

        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 9_700, target, "other")), now() - 20 * MINUTE, true);
        PublishSubject<List<MediaGroup>> rows = PublishSubject.create();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, rows);

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        setField("mCurrentVideo", mCache.groups(section, identity()).get(0).getVideos().get(0));
        rows.onNext(Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "target")));
        rows.onComplete();
        awaitFocusedCard(target);

        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(9_700, LIKED_MUSIC, 6));
        assertTrue(mView.hasSelected(target));
    }

    @Test
    public void cachedRowsKeepTheAddedHomeRowMetadataForTheirMenus() throws Exception {
        BrowseSection section = sectionOf(MediaGroup.TYPE_HOME);
        VideoGroup row = group(section, "Channel row", 0, 9_800, "row-one");
        row.setAddedHomeRow(HomeRowsData.Row.TYPE_CHANNEL, "UC-row-channel");

        seed(section, Collections.singletonList(row), now(), false);
        mPresenter.onSectionFocused(MediaGroup.TYPE_HOME);

        Video card = mView.lastGroup(9_800).getVideos().get(0);
        assertEquals("UC-row-channel", mPresenter.findAddedHomeRowChannelId(card));
        assertEquals(HomeRowsData.Row.TYPE_CHANNEL, card.getGroup().getAddedHomeRowType());
    }

    @Test
    public void completedRefreshWithNullCachedRowsDoesNotCrash() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 9_100, "old-one")), now() - 20 * MINUTE, true);
        PublishSubject<List<MediaGroup>> rows = PublishSubject.create();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, rows);

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        setField("mCachedShownGroups", null);
        rows.onNext(Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new-one")));
        rows.onComplete();

        assertEquals(0, mView.errors);
        assertTrue(mView.hasTitle(LIKED_MUSIC, 6));
    }

    @Test
    public void completedRefreshWithTheViewGoneDoesNotCrash() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 9_200, "old-one")), now() - 20 * MINUTE, true);
        PublishSubject<List<MediaGroup>> rows = PublishSubject.create();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, rows);

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        setViewGone();
        rows.onNext(Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new-one")));
        rows.onComplete();

        assertEquals(0, mView.errors);
        assertFalse(mView.hasGroup(9_200, LIKED_MUSIC, 6));
    }

    @Test
    public void accountChangeDisposesTheInFlightCachedRefresh() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 9_300, "old-one")), now() - 20 * MINUTE, true);
        PublishSubject<List<MediaGroup>> rows = PublishSubject.create();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, rows);

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        mPresenter.onAccountChanged(null);
        rows.onNext(Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new-one")));
        rows.onComplete();

        assertEquals(0, mCache.count());
        assertEquals(null, mCache.groups(section, identity()));
    }

    @Test
    public void hidingACardTakesItOutOfTheCachedSection() throws Exception {
        BrowseSection section = musicSection();
        VideoGroup liked = group(section, LIKED_MUSIC, 0, 9_400, "keep-one", "remove-one");
        seed(section, Collections.singletonList(liked), now(), false);
        AtomicInteger loads = new AtomicInteger();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, Observable.defer(() -> {
            loads.incrementAndGet();
            return Observable.just(Collections.singletonList(mediaGroup(LIKED_MUSIC, 2, "keep", MediaGroup.TYPE_MUSIC)));
        }));

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        Video hidden = mCache.groups(section, identity()).get(0).getVideos().get(1);
        mPresenter.removeItem(hidden);
        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);

        assertEquals(0, loads.get());
        VideoGroup replayed = mView.lastGroup(9_400);
        assertNotNull(replayed);
        assertEquals(1, replayed.getVideos().size());
        assertEquals("keep-one", replayed.getVideos().get(0).videoId);
        List<VideoGroup> cached = mCache.groups(section, identity());
        assertNotNull(cached);
        assertEquals(1, cached.get(0).getVideos().size());
        assertEquals("keep-one", cached.get(0).getVideos().get(0).videoId);
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
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, Observable.defer(() -> {
            mView.countRefresh();
            return Observable.just(first, second);
        }));

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        awaitRefresh();

        List<VideoGroup> cached = mCache.groups(section, identity());
        assertEquals(1, mView.refreshSubscriptions());
        assertTrue(mView.hasGroup(7_000, LIKED_MUSIC, 6));
        assertTrue(mView.hasGroup(8_000, MUSIC, 6));
        assertEquals(0, mView.errors);
        assertNotNull(cached);
        assertEquals(2, cached.size());
        assertEquals(6, cached.get(0).getVideos().size());
        assertEquals(6, cached.get(1).getVideos().size());
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
        awaitFirstChunk();

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
    public void localeChangeInvalidatesTheCacheThroughThePresenter() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 7_000, "old-one")), now(), false);

        assertEquals(1, mCache.count());

        // The sections were made in another language (see onViewInitialized)
        setField("mSectionsLocale", new Locale("zz", "ZZ"));
        mPresenter.onViewInitialized();

        assertEquals(0, mCache.count());
    }

    @Test
    public void cachedGridRefreshRestoresTheFocusedCard() throws Exception {
        BrowseSection section = sectionOf(MediaGroup.TYPE_SUBSCRIPTIONS);
        String target = "target0";

        seed(section, Collections.singletonList(group(section, "Subscriptions", -1, 9_000, target)), now() - 20 * MINUTE, true);
        putMapping("mGridMapping", MediaGroup.TYPE_SUBSCRIPTIONS,
                Observable.just(mediaGroup("Subscriptions", 15, "target", MediaGroup.TYPE_SUBSCRIPTIONS)));
        setField("mCurrentSection", section);
        setField("mCurrentVideo", mCache.groups(section, identity()).get(0).getVideos().get(0));

        updateCurrentSection();
        awaitFocusedCard(target);

        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(9_000, "Subscriptions", 15));
        assertTrue(mView.hasSelected(target));
    }

    @Test
    public void freshCacheWithAutoLoadOffKeepsTheUploadsColumn() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        MainUIData.instance(mView).setUploadsAutoLoadEnabled(false);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        VideoGroup channels = channelGroup(section, "Channels", 0, 7_300, "channel-one", "channel-two");
        VideoGroup uploads = group(section, "Uploads", 1, 7_400, "upload-one", "upload-two");

        seed(section, cachedGroups(section, channels, uploads), now(), false);
        mUploadsPresenter.setError(new RuntimeException("no uploads request on a fresh cache"));

        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        // The replayed channels make the view auto-select its first channel even when auto load is off
        mPresenter.onVideoItemSelected(channels.getVideos().get(0));

        assertEquals(0, mUploadsPresenter.calls());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(7_300, "Channels", 2));
        assertTrue(mView.hasGroup(7_400, "Uploads", 2));
        List<VideoGroup> cached = mCache.groups(section, identity());
        assertNotNull(cached);
        assertEquals(2, cached.size());
        assertEquals("Uploads", cached.get(1).getTitle());
    }

    @Test
    public void aPlaylistsStyleChangeDoesNotReplayTheCachedRows() throws Exception {
        MainUIData.instance(mView).setPlaylistsStyle(MainUIData.PLAYLISTS_STYLE_ROWS);
        mPresenter.updatePlaylistsStyle();
        BrowseSection section = sectionOf(MediaGroup.TYPE_USER_PLAYLISTS);
        assertEquals(BrowseSection.TYPE_ROW, section.getType());
        seed(section, Collections.singletonList(group(section, "Playlists", 0, 9_600, "old-playlist")), now(), false);

        MainUIData.instance(mView).setPlaylistsStyle(MainUIData.PLAYLISTS_STYLE_GRID);
        mPresenter.updatePlaylistsStyle();
        assertEquals(BrowseSection.TYPE_GRID, section.getType());
        assertNull(mCache.groups(section, identity()));

        AtomicInteger gridLoads = new AtomicInteger();
        putMapping("mGridMapping", MediaGroup.TYPE_USER_PLAYLISTS, Observable.defer(() -> {
            gridLoads.incrementAndGet();
            return Observable.just(mediaGroup("Playlists", 3, "playlist", MediaGroup.TYPE_USER_PLAYLISTS));
        }));

        mPresenter.onSectionFocused(MediaGroup.TYPE_USER_PLAYLISTS);
        awaitTitle("Playlists", 3);

        assertEquals(1, gridLoads.get());
        assertEquals(0, mView.errors);
        assertFalse(mView.hasGroup(9_600, "Playlists", 1));
    }

    @Test
    public void aCachedPlaylistsGridSurvivesTheNextPresenterStart() throws Exception {
        MainUIData.instance(mView).setPlaylistsStyle(MainUIData.PLAYLISTS_STYLE_GRID);
        BrowseSection section = sectionOf(MediaGroup.TYPE_USER_PLAYLISTS);
        assertEquals(BrowseSection.TYPE_GRID, section.getType());
        seed(section, Collections.singletonList(group(section, "Playlists", 0, 9_610, "old-playlist")), now(), false);

        // At a start the sections are made as rows first, then the Playlists style makes the grid again
        section.setType(BrowseSection.TYPE_ROW);
        mPresenter.updatePlaylistsStyle();
        assertEquals(BrowseSection.TYPE_GRID, section.getType());

        AtomicInteger gridLoads = new AtomicInteger();
        putMapping("mGridMapping", MediaGroup.TYPE_USER_PLAYLISTS, Observable.defer(() -> {
            gridLoads.incrementAndGet();
            return Observable.just(mediaGroup("Playlists", 3, "new-playlist", MediaGroup.TYPE_USER_PLAYLISTS));
        }));

        mPresenter.onSectionFocused(MediaGroup.TYPE_USER_PLAYLISTS);

        assertEquals(0, gridLoads.get());
        assertEquals(0, mView.errors);
        assertTrue(mView.hasGroup(9_610, "Playlists", 1));
        assertNotNull(mCache.groups(section, identity()));
    }

    @Test
    public void aChannelsOldLookChangeDoesNotReplayTheCachedColumns() throws Exception {
        MainUIData.instance(mView).setUploadsOldLookEnabled(false);
        BrowseSection section = sectionOf(MediaGroup.TYPE_CHANNEL_UPLOADS);
        assertEquals(BrowseSection.TYPE_MULTI_GRID, section.getType());
        VideoGroup channels = channelGroup(section, "Channels", 0, 9_900, "old-channel");
        VideoGroup uploads = group(section, "Uploads", 1, 9_901, "old-upload");
        seed(section, cachedGroups(section, channels, uploads), now(), false);

        // Channels "old look" makes the section a grid again at the next start; the multi-grid cache is for other columns
        section.setType(BrowseSection.TYPE_GRID);
        AtomicInteger gridLoads = new AtomicInteger();
        putMapping("mGridMapping", MediaGroup.TYPE_CHANNEL_UPLOADS, Observable.defer(() -> {
            gridLoads.incrementAndGet();
            return Observable.just(mediaGroup("Channels", 3, "new-channel", MediaGroup.TYPE_CHANNEL_UPLOADS));
        }));

        mPresenter.onSectionFocused(MediaGroup.TYPE_CHANNEL_UPLOADS);
        awaitTitle("Channels", 3);

        assertEquals(1, gridLoads.get());
        assertEquals(0, mView.errors);
        assertFalse(mView.hasGroup(9_900, "Channels", 1));
        assertFalse(mView.hasGroup(9_901, "Uploads", 1));
        List<VideoGroup> cached = mCache.groups(section, identity());
        assertNotNull(cached);
        assertEquals("Channels", cached.get(0).getTitle());
        assertEquals(3, cached.get(0).getVideos().size());
    }

    @Test
    public void aHistoryStyleChangeDoesNotReplayTheCachedRows() throws Exception {
        MediaServiceData.instance().setContentHidden(MediaServiceData.CONTENT_SHORTS_HISTORY_ROW, false);
        BrowseSection section = sectionOf(MediaGroup.TYPE_HISTORY);

        try {
            assertEquals(BrowseSection.TYPE_ROW, section.getType());
            seed(section, Collections.singletonList(group(section, "History", 0, 9_700, "old-video")), now(), false);

            MediaServiceData.instance().setContentHidden(MediaServiceData.CONTENT_SHORTS_HISTORY_ROW, true);
            mPresenter.updateHistoryStyle();

            assertEquals(BrowseSection.TYPE_GRID, section.getType());
            assertNull(mCache.groups(section, identity()));
        } finally {
            MediaServiceData.instance().setContentHidden(MediaServiceData.CONTENT_SHORTS_HISTORY_ROW, false);
            mPresenter.updateHistoryStyle();
        }
    }

    @Test
    public void aCardRemovedDuringAnInFlightRefreshIsNotSavedBack() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 9_500, "keep-one", "remove-one")),
                now() - 20 * MINUTE, true);
        PublishSubject<List<MediaGroup>> rows = PublishSubject.create();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, rows);

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);

        // The refresh's first part arrives and still carries the card
        rows.onNext(Collections.singletonList(mediaGroupWithIds(LIKED_MUSIC, MediaGroup.TYPE_MUSIC, "keep-one", "remove-one")));
        awaitGroup(9_500, LIKED_MUSIC, 2);
        Video hidden = mCache.groups(section, identity()).get(0).getVideos().get(1);
        assertEquals("remove-one", hidden.videoId);
        mPresenter.removeItem(hidden);

        rows.onNext(Collections.singletonList(mediaGroupWithIds(MUSIC, MediaGroup.TYPE_MUSIC, "new-two")));
        awaitTitle(MUSIC, 1);
        rows.onComplete();

        List<VideoGroup> cached = mCache.groups(section, identity());
        assertNotNull(cached);
        assertEquals(2, cached.size());
        assertEquals(1, cached.get(0).getVideos().size());
        assertEquals("keep-one", cached.get(0).getVideos().get(0).videoId);
        assertEquals("new-two", cached.get(1).getVideos().get(0).videoId);
        assertEquals(0, mView.errors);
    }

    @Test
    public void aCacheDroppedByAuthorRemovalDuringAnInFlightRefreshStaysEmpty() throws Exception {
        BrowseSection section = musicSection();
        seed(section, Collections.singletonList(group(section, LIKED_MUSIC, 0, 9_800, "author-one", "author-two")),
                now() - 20 * MINUTE, true);
        PublishSubject<List<MediaGroup>> rows = PublishSubject.create();
        putMapping("mRowMapping", MediaGroup.TYPE_MUSIC, rows);

        mPresenter.onSectionFocused(MediaGroup.TYPE_MUSIC);
        Video authorCard = mCache.groups(section, identity()).get(0).getVideos().get(0);
        removeItemAuthor(authorCard);

        rows.onNext(Collections.singletonList(mediaGroup(LIKED_MUSIC, 6, "new")));
        rows.onComplete();

        assertEquals(0, mCache.count());
        assertNull(mCache.groups(section, identity()));
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

    private void setChannelUploadsPresenter(FakeChannelUploadsPresenter presenter) throws Exception {
        Field field = ChannelUploadsPresenter.class.getDeclaredField("sInstance");
        field.setAccessible(true);
        field.set(null, presenter);
    }

    private void setViewGone() throws Exception {
        Field field = BasePresenter.class.getDeclaredField("mView");
        field.setAccessible(true);
        field.set(mPresenter, new WeakReference<>(null));
    }

    private void awaitGroup(int id, String title, int size) throws Exception {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.hasGroup(id, title, size)) {
                return;
            }

            Thread.sleep(20);
        }

        throw new AssertionError("the group didn't arrive");
    }

    /**
     * What holds a row back (a lookup or a filter set by another test) stays out: this test drives the rows of the section itself.
     */
    private void resetHoldingSettings() {
        UtubotSettings settings = UtubotSettings.instance(mView);
        settings.setUrl("");
        settings.setToken("");
        settings.setAssessEnabled(false);
        WatchLaterData.instance(mView).setMode(WatchLaterData.MODE_SHOW);
        CollaborationsData.instance(mView).setMode(CollaborationsData.MODE_SHOW);
        AiSListFilterData aiSList = AiSListFilterData.instance(mView);

        for (int list : new int[]{AiSListFilterData.LIST_BLOCKLIST, AiSListFilterData.LIST_WARNLIST}) {
            aiSList.setEverythingEnabled(list, false);

            for (int section = 0; section < AiSListFilterData.SECTION_COUNT; section++) {
                aiSList.setHideEnabled(list, section, false);
            }
        }
    }

    private BrowseSection musicSection() throws Exception {
        return sectionOf(MediaGroup.TYPE_MUSIC);
    }

    private BrowseSection sectionOf(int sectionId) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField("mSections");
        field.setAccessible(true);
        List<BrowseSection> sections = (List<BrowseSection>) field.get(mPresenter);

        for (BrowseSection section : sections) {
            if (section.getId() == sectionId) {
                return section;
            }
        }

        throw new IllegalStateException(sectionId + " isn't in the sections");
    }

    private void setField(String fieldName, Object value) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(mPresenter, value);
    }

    private void updateCurrentSection() throws Exception {
        Method method = BrowsePresenter.class.getDeclaredMethod("updateCurrentSection", boolean.class);
        method.setAccessible(true);
        method.invoke(mPresenter, false);
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

    private void awaitRefresh() throws Exception {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();
            List<VideoGroup> cached = mCache.groups(musicSection(), identity());

            if (cached != null && cached.size() == 2 && cached.get(0).getVideos().size() == 6
                    && cached.get(1).getVideos().size() == 6) {
                return;
            }

            Thread.sleep(20);
        }

        throw new AssertionError("the refresh didn't save the whole section");
    }

    private void awaitTitle(String title, int size) {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.hasTitle(title, size)) {
                return;
            }

            try {
                Thread.sleep(20);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }

        throw new AssertionError("the section didn't load");
    }

    private void removeItemAuthor(Video item) throws Exception {
        Method method = BrowsePresenter.class.getDeclaredMethod("removeItemAuthor", Video.class);
        method.setAccessible(true);
        method.invoke(mPresenter, item);
    }

    private void awaitFocusedCard(String videoId) throws Exception {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.hasSelected(videoId)) {
                return;
            }

            Thread.sleep(20);
        }

        throw new AssertionError("the refresh didn't restore the focused card");
    }

    private void awaitFirstChunk() throws Exception {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.hasGroup(7_000, LIKED_MUSIC, 6)) {
                Thread.sleep(50);
                return;
            }

            Thread.sleep(20);
        }

        throw new AssertionError("the first part didn't arrive");
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

    private static VideoGroup channelGroup(BrowseSection section, String title, int position, int id, String... channelIds) {
        List<Video> channels = new ArrayList<>();

        for (String channelId : channelIds) {
            Video channel = new Video();
            channel.channelId = channelId;
            channel.title = "Channel " + channelId;
            channel.author = "Channel " + channelId;
            channels.add(channel);
        }

        VideoGroup group = VideoGroup.from(channels, section, position);
        group.setId(id);
        group.setTitle(title);

        return group;
    }

    private static MediaGroup mediaGroup(String title, int count, String videoPrefix) {
        return mediaGroup(title, count, videoPrefix, MediaGroup.TYPE_MUSIC);
    }

    private static MediaGroup mediaGroup(String title, int count, String videoPrefix, int type) {
        String[] videoIds = new String[count];

        for (int i = 0; i < count; i++) {
            videoIds[i] = videoPrefix + i;
        }

        return mediaGroupWithIds(title, type, videoIds);
    }

    private static MediaGroup mediaGroupWithIds(String title, int type, String... videoIds) {
        List<MediaItem> items = new ArrayList<>();

        for (int i = 0; i < videoIds.length; i++) {
            items.add(mediaItem(i, title + " " + i, videoIds[i]));
        }

        return (MediaGroup) Proxy.newProxyInstance(MediaGroup.class.getClassLoader(), new Class[]{MediaGroup.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "getType":
                            return type;
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

    public static class FakeChannelUploadsPresenter extends ChannelUploadsPresenter {
        private int mCalls;
        private RuntimeException mError;
        private MediaGroup mGroup;

        public FakeChannelUploadsPresenter(Activity activity) {
            super(activity);
        }

        @Override
        public Observable<MediaGroup> obtainUploadsObservable(Video item) {
            mCalls++;

            if (mError != null) {
                return Observable.error(mError);
            }

            return mGroup != null ? Observable.just(mGroup) : Observable.never();
        }

        private int calls() {
            return mCalls;
        }

        private void setError(RuntimeException error) {
            mError = error;
        }

        private void setGroup(MediaGroup group) {
            mGroup = group;
        }
    }

    public static class FakeBrowseView extends Activity implements BrowseView {
        private final List<VideoGroup> mUpdates = new ArrayList<>();
        private final List<Video> mSelectedItems = new ArrayList<>();
        private boolean mProgressShowing;
        private int errors;
        private int refreshSubscriptions;

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

        @Override
        public void updateSectionTitle(int sectionId, String title) {
        }

        private int refreshSubscriptions() {
            return refreshSubscriptions;
        }

        private void countRefresh() {
            refreshSubscriptions++;
        }

        private boolean hasSelected(String videoId) {
            for (Video video : mSelectedItems) {
                if (videoId.equals(video.videoId)) {
                    return true;
                }
            }

            return false;
        }

        private boolean hasGroup(int id, String title, int size) {
            for (VideoGroup group : mUpdates) {
                if (group.getId() == id && title.equals(group.getTitle()) && group.getVideos().size() == size) {
                    return true;
                }
            }

            return false;
        }

        private boolean hasTitle(String title, int size) {
            for (VideoGroup group : mUpdates) {
                if (title.equals(group.getTitle()) && group.getVideos().size() == size) {
                    return true;
                }
            }

            return false;
        }

        private VideoGroup lastGroup(int id) {
            for (int i = mUpdates.size() - 1; i >= 0; i--) {
                VideoGroup group = mUpdates.get(i);

                if (group.getId() == id) {
                    return group;
                }
            }

            return null;
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
