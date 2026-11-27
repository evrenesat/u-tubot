package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutPromptQueue.Answer;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutPromptQueue.Item;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowToast;

import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * The app-wide ready cut (issue 96): it is not asked when the player owns the cut, it is asked on whatever screen comes next when this
 * TV ordered it elsewhere, Yes opens it, No or Back leaves the viewer where they are, and a failure waits for the next screen. While the
 * picker is still open for the video it refreshes that picker instead of starting the video (issue 197); and a cut ordered from the
 * thumbnail screen opens by itself when ready, but only while the owner is still browsing (a card focused, no video playing) — focus
 * moved to other content, or a video playing, is asked instead, never interrupting the playing video.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutNoticesTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String OTHER_VIDEO = "jNQXAC9IVRw";
    private static final String REQUEST = "cut1";
    private static final String TITLE = "The demo";

    private final List<Activity> mScreens = new ArrayList<>();
    private Context mContext;
    private Activity mActivity;
    private UtubotCutNotices mNotices;
    private TestDialog mDialog;
    private AppDialogPresenter mPreviousDialog;
    private UtubotManager mManager;
    private Object mPreviousFollower;
    private PlaybackPresenter mPresenter;
    private List<PlayerEventListener> mEventListeners;
    private List<PlayerEventListener> mPreviousListeners;
    private TestCutController mController;

    @Before
    public void setUp() throws Exception {
        mContext = RuntimeEnvironment.getApplication();
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        ShadowToast.reset();
        UtubotCutWaitlist.prefs(mContext).clear();
        UtubotCutFocus.set(null);
        setStatic(UtubotMenu.class, "sOpenVideoId", null);

        setStatic(UtubotCutNotices.class, "sInstance", null);
        mNotices = UtubotCutNotices.instance(mContext);

        mPreviousDialog = (AppDialogPresenter) getStatic(AppDialogPresenter.class, "sInstance");
        mDialog = new TestDialog(mContext);
        setStatic(AppDialogPresenter.class, "sInstance", mDialog);

        mManager = UtubotManager.instance(mContext);
        mPreviousFollower = getField(mManager, "mCutsFollower");
        setField(mManager, "mCutsFollower", null);

        mPresenter = PlaybackPresenter.instance(mActivity);
        mEventListeners = (List<PlayerEventListener>) getField(mPresenter, "mEventListeners");
        mPreviousListeners = new ArrayList<>(mEventListeners);
        mController = new TestCutController();
        mEventListeners.clear();
        mEventListeners.add(mController);
    }

    @After
    public void tearDown() throws Exception {
        for (Activity screen : mScreens) {
            UtubotScreen.onPaused(screen);
        }

        setField(mManager, "mCutsFollower", mPreviousFollower);
        mEventListeners.clear();
        mEventListeners.addAll(mPreviousListeners);
        setStatic(AppDialogPresenter.class, "sInstance", mPreviousDialog);
        setStatic(UtubotCutNotices.class, "sInstance", null);
        ShadowToast.reset();
    }

    @Test
    public void aCutOfTheVideoThatPlays_thatThePlayerFollows_isNotAsked() throws Exception {
        foreground();
        mController.open(video(VIDEO), 240_000);
        followedRequest(REQUEST);

        mNotices.onCutReady(entry(), cut());

        assertNull(mDialog.text);
    }

    @Test
    public void aCutOfTheVideoThatPlays_orderedElsewhere_isAnnouncedNotAsked() {
        foreground();
        mController.open(video(VIDEO), 240_000);

        mNotices.onCutReady(entry(), cut());

        assertFalse(mDialog.shown); // no modal over the playing video
        assertEquals(mContext.getString(R.string.utubot_cut_ready_later, TITLE, "3:12"), ShadowToast.getTextOfLatestToast());
        assertNull(mController.appliedOnOpen());
    }

    @Test
    public void aSecondCutOfTheVideoThatPlays_isAnnouncedWhileThePlayerFollowsAnother() throws Exception {
        foreground();
        mController.open(video(VIDEO), 240_000);
        followedRequest("cut2");

        mNotices.onCutReady(entry(), cut());

        assertFalse(mDialog.shown);
        assertEquals(mContext.getString(R.string.utubot_cut_ready_later, TITLE, "3:12"), ShadowToast.getTextOfLatestToast());
    }

    @Test
    public void aCutOfAnotherVideoThatPlays_isAnnouncedNotAskedOverIt() {
        foreground();
        mController.open(video(OTHER_VIDEO), 240_000);

        mNotices.onCutReady(entry(), cut());

        assertFalse(mDialog.shown);
        assertEquals(mContext.getString(R.string.utubot_cut_ready_later, TITLE, "3:12"), ShadowToast.getTextOfLatestToast());
    }

    @Test
    public void aCutThePlayerAlreadyApplied_isNotAsked() {
        foreground();
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut();
        assertTrue(mController.toggle(cut));

        mNotices.onCutReady(entry(), cut);

        assertNull(mDialog.text);
    }

    @Test
    public void aCutThePlayerIsWaitingToApply_isNotAsked() {
        foreground();
        mController.open(video(VIDEO), 0);
        Cut cut = cut();
        assertTrue(mController.toggle(cut));

        mNotices.onCutReady(entry(), cut);

        assertNull(mDialog.text);
    }

    /**
     * A cut the player's follower offered with Apply (the request was cleared when it became ready) is not asked again: the notice
     * must read the offer as the player already handling the cut, not a second, waiting question.
     */
    @Test
    public void aReadyCutThePlayerIsOffering_isNotAsked() throws Exception {
        foreground();
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut();
        setField(mController, "mOfferingCut", cut);

        mNotices.onCutReady(entry(), cut);

        assertNull(mDialog.text);
    }

    @Test
    public void aCutFoundWhileTheAppIsInTheBackground_isNotAskedAtTheNextScreen() {
        mNotices.onCutReady(entry(), cut());

        foreground();
        mNotices.onScreenAvailable();

        assertNull(mDialog.text);
    }

    //region A cut ordered from the thumbnail screen, issue 197

    @Test
    public void aCutReadyWhileFocusedOnItsVideo_opensByItself() {
        foreground();
        UtubotCutFocus.set(VIDEO); // a card of the browse screen is focused, no video playing: the owner is waiting for it
        Cut cut = cut();

        mNotices.onCutReady(entry(), cut);

        assertNull(mDialog.text); // no question modal
        assertSame(cut, mController.appliedOnOpen()); // carried to the player
        assertEquals(VIDEO, mPresenter.getVideo().videoId); // the cut's video opens by itself
    }

    @Test
    public void aCutReadyWhileBrowsing_opensByItself() {
        foreground();
        UtubotCutFocus.set(OTHER_VIDEO); // still browsing thumbnails: a different card is focused, but no video is playing
        Cut cut = cut();

        mNotices.onCutReady(entry(), cut);

        assertNull(mDialog.text);
        assertSame(cut, mController.appliedOnOpen());
        assertEquals(VIDEO, mPresenter.getVideo().videoId);
    }

    @Test
    public void aCutReadyAfterTheFocusMovedAway_isAsked() {
        foreground();
        UtubotCutFocus.set(null); // the focus is no longer on a card of the browse screen: the owner moved to other content

        mNotices.onCutReady(entry(), cut());

        assertEquals(mContext.getString(R.string.utubot_cut_ready_play, TITLE, "3:12"), mDialog.question);
        assertNull(mController.appliedOnOpen());
    }

    @Test
    public void aCutReadyWhileAnotherVideoPlays_isNotForcedOnThePlayingVideo() {
        foreground();
        mController.open(video(OTHER_VIDEO), 240_000); // a different video is playing
        UtubotCutFocus.set(VIDEO); // a stale card focus must not start a cut over the video that plays

        mNotices.onCutReady(entry(), cut());

        assertFalse(mDialog.shown);
        assertEquals(mContext.getString(R.string.utubot_cut_ready_later, TITLE, "3:12"), ShadowToast.getTextOfLatestToast());
        assertNull(mController.appliedOnOpen());
    }

    @Test
    public void theOpenCutMenuReopensInsteadOfStartingTheVideo() throws Exception {
        foreground();
        UtubotCutFocus.set(VIDEO);
        setStatic(UtubotMenu.class, "sOpenVideoId", VIDEO); // the cut picker is open for this video

        mNotices.onCutReady(entry(), cut());

        assertNull(mDialog.text); // not asked
        assertNull(mController.appliedOnOpen()); // not started
        assertTrue(UtubotMenu.isCutsMenuOpen(VIDEO)); // the picker is still up, refreshed with the ready state
    }

    //endregion

    @Test
    public void theQuestionSaysTheTitleAndTheRealLength() {
        foreground();

        assertTrue(mNotices.presentPrompt(new Item(entry(), cut()), new TestAnswer()));

        assertEquals(mContext.getString(R.string.utubot_cut_ready_play, TITLE, "3:12"), mDialog.question);
        assertNull(mDialog.text); // the title is hidden over a playing video: the question must not depend on it
        assertEquals(2, mDialog.items.size());
        assertEquals(mContext.getString(R.string.utubot_cut_play_yes), mDialog.items.get(0).getTitle());
        assertEquals(mContext.getString(R.string.utubot_cut_play_no), mDialog.items.get(1).getTitle());
        assertTrue(mDialog.transparent);
        assertFalse(mDialog.expandable);
    }

    @Test
    public void anUnknownLength_isLeftOut() {
        foreground();
        Cut cut = cut();
        cut.keptMs = UtubotModels.UNKNOWN;

        mNotices.presentPrompt(new Item(entry(), cut), new TestAnswer());

        assertEquals(mContext.getString(R.string.utubot_cut_ready_play_no_length, TITLE), mDialog.question);
    }

    @Test
    public void yesClosesTheQuestionAndPlaysTheCut() {
        foreground();
        TestAnswer answer = new TestAnswer();
        mNotices.presentPrompt(new Item(entry(), cut()), answer);

        mDialog.items.get(0).onSelect(true);

        assertTrue(answer.played);
        assertFalse(answer.stayed);
        assertFalse(mDialog.shown);
    }

    @Test
    public void noClosesTheQuestionAndStaysWhereTheViewerIs() {
        foreground();
        TestAnswer answer = new TestAnswer();
        mNotices.presentPrompt(new Item(entry(), cut()), answer);

        mDialog.items.get(1).onSelect(true);

        assertFalse(answer.played);
        assertTrue(answer.stayed);
        assertFalse(mDialog.shown);
    }

    /**
     * Yes goes through the real queue: the controller carries the cut to the open (applyOnOpen) and the presenter opens the cut's video
     * with its title, not a list add that would hide a null controller/context regression in openWithCut.
     */
    @Test
    public void theYesPathCarriesTheCutThroughTheRealOpen() throws Exception {
        foreground();
        Cut cut = cut(); // browsing, nothing plays: the ready cut is asked
        mNotices.onCutReady(entry(), cut);

        mDialog.items.get(0).onSelect(true); // Yes, through the real queue and openWithCut

        assertTrue(promptQueue().isEmpty());
        assertSame(cut, mController.appliedOnOpen());
        Video opened = mPresenter.getVideo();
        assertNotNull(opened);
        assertEquals(VIDEO, opened.videoId);
        assertEquals(TITLE, opened.title);
    }

    /**
     * A ready cut the player took over (applied) after the question was kept is dropped at the next try, not shown again over the cut
     * the player already has.
     */
    @Test
    public void aCutThePlayerGainedAfterItWasKept_isDroppedAtTheNextTry() throws Exception {
        foreground();
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut();
        assertTrue(mController.toggle(cut)); // the player applies the cut after the question was kept

        promptQueue().add(new Item(entry(), cut));

        assertNull(mDialog.text); // dropped: the player already has the cut
        assertTrue(promptQueue().isEmpty());
    }

    @Test
    public void backClosesTheQuestionAndStaysWhereTheViewerIs() {
        foreground();
        TestAnswer answer = new TestAnswer();
        mNotices.presentPrompt(new Item(entry(), cut()), answer);

        mDialog.finish();

        assertFalse(answer.played);
        assertTrue(answer.stayed);
        assertFalse(mDialog.shown);
    }

    @Test
    public void aFailureWhileTheAppIsInTheBackground_isShownAtTheNextScreen() {
        mNotices.onCutFailed(entry(), "no transcript");

        assertNull(ShadowToast.getTextOfLatestToast());

        foreground();
        mNotices.onScreenAvailable();

        assertEquals(mContext.getString(R.string.utubot_cut_failed, "no transcript"), ShadowToast.getTextOfLatestToast());
    }

    @Test
    public void aFailureWithoutAReason_saysOnlyThatItFailed() {
        foreground();

        mNotices.onCutFailed(entry(), null);

        assertEquals(mContext.getString(R.string.utubot_cut_failed_plain), ShadowToast.getTextOfLatestToast());
    }

    @Test
    public void theQuestionGoesOverTheScreenThatComesNext() {
        Activity first = foreground();
        UtubotScreen.onPaused(first);
        Activity second = Robolectric.buildActivity(Activity.class).setup().get();
        UtubotScreen.onResumed(second, false);
        mScreens.add(first);
        mScreens.add(second);

        mNotices.onCutReady(entry(), cut());

        assertSame(second, mDialog.lastContext);
    }

    private Activity foreground() {
        UtubotScreen.onResumed(mActivity, false);
        mScreens.add(mActivity);

        return mActivity;
    }

    private void followedRequest(String requestId) throws Exception {
        UtubotCutFollower follower = new UtubotCutFollower(null, null, null);
        setField(follower, "mRequestId", requestId);
        setField(mManager, "mCutsFollower", follower);
    }

    private UtubotCutPromptQueue promptQueue() throws Exception {
        return (UtubotCutPromptQueue) getField(mNotices, "mPrompts");
    }

    private static Entry entry() {
        return new Entry(REQUEST, VIDEO, TITLE, 0);
    }

    private static Cut cut() {
        Cut cut = new Cut();
        cut.videoId = VIDEO;
        cut.label = "No filler";
        cut.durationMs = 240_000;
        cut.keptMs = 192_000;

        return cut;
    }

    private static Video video(String videoId) {
        Video video = new Video();
        video.videoId = videoId;

        return video;
    }

    private static Object getField(Object target, String name) throws Exception {
        for (Class<?> type = target.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);

                return field.get(target);
            } catch (NoSuchFieldException missing) {
                // The field is higher up the hierarchy: keep looking
            }
        }

        throw new NoSuchFieldException(name);
    }

    private static void setField(Object target, String name, Object value) throws Exception {
        for (Class<?> type = target.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                field.set(target, value);

                return;
            } catch (NoSuchFieldException missing) {
                // The field is higher up the hierarchy: keep looking
            }
        }

        throw new NoSuchFieldException(name);
    }

    private static Object getStatic(Class<?> type, String name) throws Exception {
        Field field = type.getDeclaredField(name);
        field.setAccessible(true);

        return field.get(null);
    }

    private static void setStatic(Class<?> type, String name, Object value) throws Exception {
        Field field = type.getDeclaredField(name);
        field.setAccessible(true);
        field.set(null, value);
    }

    private static final class TestAnswer implements Answer {
        private boolean played;
        private boolean stayed;

        @Override
        public void play() {
            played = true;
        }

        @Override
        public void stay() {
            stayed = true;
        }
    }

    private static final class TestDialog extends AppDialogPresenter {
        private final List<OptionItem> items = new ArrayList<>();
        private CharSequence text;
        private CharSequence question;
        private boolean shown;
        private boolean transparent;
        private boolean expandable = true;
        private Context lastContext;
        private Runnable onFinish;

        TestDialog(Context context) {
            super(context);
        }

        @Override
        public void setContext(Context context) {
            super.setContext(context);
            lastContext = context;
        }

        @Override
        public void appendSingleButton(OptionItem optionItem) {
            items.add(optionItem);
        }

        @Override
        public void appendLongTextCategory(CharSequence categoryTitle, OptionItem item) {
            question = item.getTitle();
        }

        @Override
        public void setId(int id) {
        }

        @Override
        public void setOnFinish(Runnable onFinish) {
            this.onFinish = onFinish;
        }

        @Override
        public void enableTransparent(boolean enable) {
            transparent = enable;
        }

        @Override
        public void enableExpandable(boolean enable) {
            expandable = enable;
        }

        @Override
        public boolean isDialogShown() {
            return shown;
        }

        @Override
        public void showDialog(CharSequence dialogTitle, Runnable onFinish) {
            text = dialogTitle;
            shown = true;
        }

        @Override
        public void closeDialog() {
            finish();
        }

        void finish() {
            shown = false;

            if (onFinish != null) {
                onFinish.run();
                onFinish = null;
            }
        }
    }

    private static final class TestCutController extends UtubotCutController {
        private Video mVideo;
        private PlaybackView mPlayer;
        private Cut mAppliedOnOpen;

        void open(Video video, long durationMs) {
            mVideo = video;
            mPlayer = player(durationMs);
        }

        @Override
        public void applyOnOpen(Cut cut) {
            mAppliedOnOpen = cut;
            super.applyOnOpen(cut);
        }

        Cut appliedOnOpen() {
            return mAppliedOnOpen;
        }

        @Override
        public Video getVideo() {
            return mVideo;
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }
    }

    private static PlaybackView player(long durationMs) {
        return (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                (proxy, method, args) -> {
                    if ("getDurationMs".equals(method.getName())) {
                        return durationMs;
                    }

                    if ("isEngineInitialized".equals(method.getName())) {
                        return true;
                    }

                    Class<?> type = method.getReturnType();

                    if (type == boolean.class) {
                        return false;
                    } else if (type == int.class) {
                        return 0;
                    } else if (type == long.class) {
                        return 0L;
                    } else if (type == float.class) {
                        return 0f;
                    }

                    return null;
                });
    }
}
