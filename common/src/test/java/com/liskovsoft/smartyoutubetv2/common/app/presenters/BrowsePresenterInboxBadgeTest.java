package com.liskovsoft.smartyoutubetv2.common.app.presenters;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.R;
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
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotProcessedSection;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotInboxSection;
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

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import io.reactivex.Observable;
import io.reactivex.subjects.PublishSubject;

import static org.junit.Assert.assertEquals;

/**
 * The Inbox's unread badge (u-tubot #160): the rail shows new results without opening the section. The badge is set while the Inbox is
 * not open (a result ready while watching), cleared while it is open, and refreshed when the browse UI returns. A presenter-level test,
 * with a fake view and no backend: the glue that owns the badge had none, which is why the "while open" guard left it unreachable.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class BrowsePresenterInboxBadgeTest {
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
    public void aResultReadyWhileWatchingShowsTheBadgeOnTheRail() throws Exception {
        PublishSubject inbox = subject();
        putInboxMapping(inbox);
        putProcessedMapping(Observable.just(new ProcessedList()));

        // The viewer is on another section (a cut just finished): the Inbox is not open, so a ready result shows on the rail
        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        inbox.onNext(list(2));
        ShadowLooper.idleMainLooper();

        assertEquals(mView.getString(R.string.utubot_inbox_badge, 2), mView.lastSectionTitle(UtubotInboxSection.ID));
    }

    @Test
    public void theBadgeClearsWhenTheInboxIsOpen() throws Exception {
        PublishSubject inbox = subject();
        putInboxMapping(inbox);
        putProcessedMapping(Observable.just(new ProcessedList()));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        inbox.onNext(list(2));
        ShadowLooper.idleMainLooper();
        assertEquals(mView.getString(R.string.utubot_inbox_badge, 2), mView.lastSectionTitle(UtubotInboxSection.ID));

        // Open the Inbox: the results are on the screen, so the badge clears (the count is shared per user, so it clears on the phone
        // and the extension too)
        setField("mCurrentSection", sectionOf(UtubotInboxSection.ID));
        inbox.onNext(list(2));
        ShadowLooper.idleMainLooper();

        assertEquals(mView.getString(R.string.utubot_inbox_title), mView.lastSectionTitle(UtubotInboxSection.ID));
    }

    @Test
    public void anUnreadThatClearedClearsTheBadgeToo() throws Exception {
        PublishSubject inbox = subject();
        putInboxMapping(inbox);
        putProcessedMapping(Observable.just(new ProcessedList()));

        mPresenter.onSectionFocused(UtubotProcessedSection.ID);
        inbox.onNext(list(1));
        ShadowLooper.idleMainLooper();
        assertEquals(mView.getString(R.string.utubot_inbox_badge, 1), mView.lastSectionTitle(UtubotInboxSection.ID));

        // The viewer read it on the phone: the next refresh sees no unread and the badge is gone
        inbox.onNext(list(0));
        ShadowLooper.idleMainLooper();

        assertEquals(mView.getString(R.string.utubot_inbox_title), mView.lastSectionTitle(UtubotInboxSection.ID));
    }

    private PublishSubject subject() {
        return PublishSubject.create();
    }

    private void resetSidebar() {
        AppPrefs.instance(mView).setSidebarData("");
        SidebarService sidebar = getSidebar();
        sidebar.onProfileChanged();
        sidebar.enableSection(UtubotProcessedSection.ID, true);
        sidebar.enableSection(UtubotInboxSection.ID, true);
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

    private void setField(String fieldName, Object value) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(mPresenter, value);
    }

    private void putInboxMapping(Observable<?> observable) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField("mInboxMapping");
        field.setAccessible(true);
        Map<Integer, Observable<?>> map = (Map<Integer, Observable<?>>) field.get(mPresenter);
        map.put(UtubotInboxSection.ID, observable);
    }

    private void putProcessedMapping(Observable<?> observable) throws Exception {
        Field field = BrowsePresenter.class.getDeclaredField("mProcessedMapping");
        field.setAccessible(true);
        Map<Integer, Observable<?>> map = (Map<Integer, Observable<?>>) field.get(mPresenter);
        map.put(UtubotProcessedSection.ID, observable);
    }

    private static InboxList list(int unread) {
        InboxList list = new InboxList();
        list.unread = unread;
        list.items = new ArrayList<>();
        return list;
    }

    public static class FakeBrowseView extends Activity implements BrowseView {
        private final List<VideoGroup> mUpdates = new ArrayList<>();
        private final Map<Integer, String> mSectionTitles = new HashMap<>();
        private boolean lastProgress;

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
            mSectionTitles.put(sectionId, title);
        }

        private String lastSectionTitle(int sectionId) {
            return mSectionTitles.get(sectionId);
        }
    }
}
