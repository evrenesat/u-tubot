package com.liskovsoft.smartyoutubetv2.common.app.presenters;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.ErrorFragmentData;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.service.SidebarService;
import com.liskovsoft.smartyoutubetv2.common.app.views.BrowseView;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotBrowseCache;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutState;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.JobState;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCaption;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotProcessedSection;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;

import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import io.reactivex.Observable;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The presenter's side of the Processed section, with a fake view and no backend: its registration, the tiles loaded from an
 * injected answer, the empty and failed states. Follows BrowsePresenterCacheTest's style.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class BrowsePresenterProcessedTest {
    private FakeBrowseView mView;
    private BrowsePresenter mPresenter;
    private UtubotBrowseCache mCache;

    @Before
    public void setUp() throws Exception {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        BrowsePresenter.unhold();
        mView = Robolectric.buildActivity(FakeBrowseView.class).setup().get();
        UtubotSettings settings = UtubotSettings.instance(mView);
        settings.setUrl("http://127.0.0.1:9");
        settings.setToken("test-token");
        resetSidebar();
        mPresenter = BrowsePresenter.instance(mView);
        mPresenter.setView(mView);
        mPresenter.onViewInitialized();
        mCache = UtubotBrowseCache.instance(mView);
        mCache.invalidate();
    }

    @After
    public void tearDown() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mView);
        settings.setUrl("");
        settings.setToken("");

        if (mCache != null) {
            mCache.invalidate();
        }
        BrowsePresenter.unhold();
    }

    @Test
    public void theSidebarRegistersTheSectionOnlyInTheBuiltInFlavor() throws Exception {
        BrowseSection section = sectionOf(UtubotProcessedSection.ID);

        assertEquals(UtubotProcessedSection.ID, section.getId());
        assertEquals("Processed", section.getTitle());
        assertEquals(BrowseSection.TYPE_GRID, section.getType());
        assertNotNull(section.getMessage());
        assertTrue(getSidebar().getDefaultSections().containsValue(UtubotProcessedSection.ID));
    }

    @Test
    public void theSectionLoadsTheBackendsTilesNewestFirst() throws Exception {
        ProcessedList list = list(item("newest", "Newest video", JobState.READY, CutState.READY, "Only the demo", true),
                item("older", "Older video", JobState.PROCESSING, CutState.BUILDING, "Keep the demo", false));
        putMapping(UtubotProcessedSection.ID, Observable.just(list));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        awaitTitle("Processed", 2);

        VideoGroup group = mView.lastTitle("Processed", 2);
        assertNotNull(group);
        assertEquals(UtubotProcessedSection.ID, group.getSection().getId());

        List<Video> videos = group.getVideos();
        assertEquals(Arrays.asList("newest", "older"), videoIds(group));
        assertEquals("Newest video", videos.get(0).title);
        assertEquals("newest", videos.get(0).videoId);
        assertEquals("HQ captions: ready • Cut ready: Only the demo • Summary ready", videos.get(0).secondTitle.toString());
        assertEquals("HQ captions: processing • Cut building: Keep the demo", videos.get(1).secondTitle.toString());
        assertEquals(0, mView.errors);
    }

    @Test
    public void anEmptyAnswerShowsTheSectionsEmptyState() throws Exception {
        putMapping(UtubotProcessedSection.ID, Observable.just(new ProcessedList()));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        awaitErrors(1);

        assertEquals("No processed videos yet", mView.lastError.getMessage());
        assertFalse(mView.lastProgress);
    }

    @Test
    public void aFailedAnswerShowsTheSectionsFailureState() throws Exception {
        putMapping(UtubotProcessedSection.ID, Observable.error(new RuntimeException("the backend is down")));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        awaitErrors(1);

        assertEquals("Can't load the processed videos: the backend is down", mView.lastError.getMessage());
        assertFalse(mView.lastProgress);
    }

    @Test
    public void aFailedAnswerWithTheViewGoneDoesNotRaiseAnError() throws Exception {
        putMapping(UtubotProcessedSection.ID, Observable.error(new RuntimeException("the backend is down")));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        setViewGone();
        ShadowLooper.idleMainLooper();

        assertEquals(0, mView.errors);
    }

    @Test
    public void aChangedConnectionDoesNotReplayTheOldUsersCachedTiles() throws Exception {
        putMapping(UtubotProcessedSection.ID, Observable.just(list(
                item("only-a", "A's video", JobState.READY, CutState.READY, "Only the demo", true))));
        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        awaitTitle("Processed", 1);
        assertNotNull(mCache.groups(sectionOf(UtubotProcessedSection.ID), browseCacheIdentity()));

        int updatesBefore = mView.updateCount();
        UtubotSettings settings = UtubotSettings.instance(mView);
        settings.setUrl("https://utubot.example.com");
        settings.setToken("user-b-token");

        assertEquals(updatesBefore, mView.updateCount());
        assertNull(mCache.groups(sectionOf(UtubotProcessedSection.ID), browseCacheIdentity()));

        putMapping(UtubotProcessedSection.ID, Observable.just(list(
                item("only-b", "B's video", JobState.PROCESSING, CutState.BUILDING, "Keep the demo", false))));
        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        awaitVideo("only-b");

        for (VideoGroup group : mView.updatesSince(updatesBefore)) {
            if ("Processed".equals(group.getTitle()) && !group.isEmpty()) {
                assertEquals("only-b", group.getVideos().get(0).videoId);
            }
        }
    }

    @Test
    public void anUnconfiguredBackendShowsTheSetupHint() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mView);
        settings.setUrl("");
        settings.setToken("");
        putMapping(UtubotProcessedSection.ID, Observable.error(new RuntimeException("Bad backend address: ")));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        awaitErrors(1);

        assertEquals("Set the u·tubot backend address in the settings first", mView.lastError.getMessage());
        assertFalse(mView.lastProgress);
    }

    private void setViewGone() throws Exception {
        Field field = BasePresenter.class.getDeclaredField("mView");
        field.setAccessible(true);
        field.set(mPresenter, new WeakReference<>(null));
    }

    private void resetSidebar() {
        AppPrefs.instance(mView).setSidebarData("");
        SidebarService sidebar = getSidebar();
        sidebar.onProfileChanged();
        sidebar.enableSection(UtubotProcessedSection.ID, true);
    }

    private SidebarService getSidebar() {
        return SidebarService.instance(mView);
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

    private String browseCacheIdentity() throws Exception {
        Method method = BrowsePresenter.class.getDeclaredMethod("getBrowseCacheIdentity");
        method.setAccessible(true);

        return (String) method.invoke(mPresenter);
    }

    private void putMapping(int sectionId, Observable<?> observable) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField("mProcessedMapping");
        field.setAccessible(true);
        Map<Integer, Observable<?>> map = (Map<Integer, Observable<?>>) field.get(mPresenter);
        map.put(sectionId, observable);
    }

    private void awaitTitle(String title, int size) {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.hasTitle(title, size)) {
                return;
            }

            sleep();
        }

        throw new AssertionError("the section didn't load");
    }

    private void awaitVideo(String videoId) {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.hasVideo(videoId)) {
                return;
            }

            sleep();
        }

        throw new AssertionError(videoId + " didn't load");
    }

    private void awaitErrors(int count) {
        long deadline = System.currentTimeMillis() + 5_000;

        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();

            if (mView.errors >= count) {
                return;
            }

            sleep();
        }

        throw new AssertionError("the error didn't show");
    }

    private static void sleep() {
        try {
            Thread.sleep(20);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static ProcessedList list(ProcessedItem... items) {
        ProcessedList list = new ProcessedList();
        list.videos = new ArrayList<>(Arrays.asList(items));
        return list;
    }

    private static ProcessedItem item(String videoId, String title, String captionState, String cutState,
                                      String presetLabel, boolean summary) {
        ProcessedItem item = new ProcessedItem();
        item.videoId = videoId;
        item.title = title;
        item.summary = summary;
        ProcessedCaption caption = new ProcessedCaption();
        caption.jobId = videoId + "-caption";
        caption.state = captionState;
        item.captions = Collections.singletonList(caption);
        ProcessedCut cut = new ProcessedCut();
        cut.requestId = videoId + "-cut";
        cut.state = cutState;
        cut.presetLabel = presetLabel;
        item.cuts = Collections.singletonList(cut);
        return item;
    }

    private static List<String> videoIds(VideoGroup group) {
        List<String> ids = new ArrayList<>();

        for (Video video : group.getVideos()) {
            ids.add(video.videoId);
        }

        return ids;
    }

    public static class FakeBrowseView extends Activity implements BrowseView {
        private final List<VideoGroup> mUpdates = new ArrayList<>();
        private int errors;
        private boolean lastProgress;
        private ErrorFragmentData lastError;

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
        }

        @Override
        public void showError(ErrorFragmentData data) {
            errors++;
            lastError = data;
        }

        @Override
        public void showProgressBar(boolean show) {
            lastProgress = show;
        }

        @Override
        public boolean isProgressBarShowing() {
            return lastProgress;
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

        private boolean hasTitle(String title, int size) {
            for (VideoGroup group : mUpdates) {
                if (title.equals(group.getTitle()) && group.getVideos().size() == size) {
                    return true;
                }
            }

            return false;
        }

        private boolean hasVideo(String videoId) {
            for (VideoGroup group : mUpdates) {
                for (Video video : group.getVideos()) {
                    if (videoId.equals(video.videoId)) {
                        return true;
                    }
                }
            }

            return false;
        }

        private int updateCount() {
            return mUpdates.size();
        }

        private List<VideoGroup> updatesSince(int index) {
            return new ArrayList<>(mUpdates.subList(index, mUpdates.size()));
        }

        private VideoGroup lastTitle(String title, int size) {
            for (int i = mUpdates.size() - 1; i >= 0; i--) {
                VideoGroup group = mUpdates.get(i);

                if (title.equals(group.getTitle()) && group.getVideos().size() == size) {
                    return group;
                }
            }

            return null;
        }
    }
}
