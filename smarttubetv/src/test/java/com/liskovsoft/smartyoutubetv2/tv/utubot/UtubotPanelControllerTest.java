package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.app.Application;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.tv.R;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;
import org.robolectric.shadows.ShadowLooper;

import java.util.concurrent.TimeUnit;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * The passive panel on a screen with cards: where it shows, when it hides, what Back does. The clock is the looper's.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotPanelControllerTest {
    private static final int DELAY_MS = UtubotSettings.DEFAULT_PANEL_DELAY_MS;
    private Activity mActivity;
    private UtubotPanelController mController;
    private FrameLayout mCards;
    private View mFirstCard;
    private View mSecondCard;
    private View mSidebar;

    /**
     * A screen like the browse ones: a sidebar and the cards, laid out before the window shows
     */
    public static final class ScreenActivity extends Activity {
        View sidebar;
        View firstCard;
        View secondCard;
        FrameLayout cards;

        @Override
        protected void onCreate(android.os.Bundle savedInstanceState) {
            super.onCreate(savedInstanceState);
            FrameLayout screen = new FrameLayout(this);
            sidebar = focusable(this, null);
            firstCard = focusable(this, video("aaaaaaaaaaa", "First"));
            secondCard = focusable(this, video("bbbbbbbbbbb", "Second"));
            cards = new FrameLayout(this);
            cards.addView(firstCard, new FrameLayout.LayoutParams(300, 200));
            cards.addView(secondCard, new FrameLayout.LayoutParams(300, 200));
            screen.addView(sidebar, new FrameLayout.LayoutParams(100, 200));
            screen.addView(cards, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            setContentView(screen);
        }
    }

    @Before
    public void setUp() {
        ScreenActivity activity = Robolectric.buildActivity(ScreenActivity.class).setup().get();
        mActivity = activity;
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("http://127.0.0.1:1");
        settings.setToken("token");
        settings.setSummaryPanelEnabled(true);
        settings.setPanelDelayMs(DELAY_MS);
        mSidebar = activity.sidebar;
        mFirstCard = activity.firstCard;
        mSecondCard = activity.secondCard;
        mCards = activity.cards;
    }

    private static View focusable(Activity activity, Video video) {
        View view = new View(activity);
        view.setFocusable(true);

        if (video != null) {
            view.setTag(R.id.utubot_card_video, video);
        }

        return view;
    }

    private static Video video(String id, String title) {
        Video video = new Video();
        video.videoId = id;
        video.title = title;

        return video;
    }

    @After
    public void tearDown() {
        if (mController != null) {
            mController.onDestroy();
        }
    }

    private void resume() {
        mController = new UtubotPanelController(mActivity);
        mController.onResume();
        idle(0);
    }

    private View focus() {
        return mActivity.getWindow().getDecorView().findFocus();
    }

    private static void idle(long ms) {
        ShadowLooper.idleMainLooper(ms, TimeUnit.MILLISECONDS);
    }

    private UtubotPanelView panel() {
        ViewGroup content = mActivity.findViewById(android.R.id.content);

        for (int i = 0; i < content.getChildCount(); i++) {
            if (content.getChildAt(i) instanceof UtubotPanelView) {
                return (UtubotPanelView) content.getChildAt(i);
            }
        }

        throw new AssertionError("no panel in the content");
    }

    private static KeyEvent down(int key) {
        return new KeyEvent(KeyEvent.ACTION_DOWN, key);
    }

    private static KeyEvent up(int key) {
        return new KeyEvent(KeyEvent.ACTION_UP, key);
    }

    @Test
    public void aCardThatKeepsTheFocusBringsThePanelWithItsTitleAtOnce() {
        resume();
        assertNotNull(panel());
        assertEquals(View.GONE, panel().getVisibility());

        mFirstCard.requestFocus();
        idle(0);

        assertEquals(View.VISIBLE, panel().getVisibility());
        assertSame(mFirstCard, focus());
    }

    @Test
    public void theFirstBackHidesThePanelAndKeepsTheFocusOnTheCard() {
        resume();
        mFirstCard.requestFocus();
        idle(DELAY_MS + 100);
        assertEquals(View.VISIBLE, panel().getVisibility());

        boolean used = mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_BACK));

        assertTrue(used);
        assertEquals(View.GONE, panel().getVisibility());
        assertSame(mFirstCard, focus());
        assertTrue("the release of the used press is swallowed too", mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_BACK)));
    }

    @Test
    public void theNextBackIsTheAppsOwn() {
        resume();
        mFirstCard.requestFocus();
        idle(DELAY_MS + 100);
        mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_BACK));
        mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_BACK));

        assertFalse(mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_BACK)));
        assertFalse(mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_BACK)));
        assertSame(mFirstCard, focus());
    }

    @Test
    public void backWithoutAPanelIsTheAppsOwn() {
        resume();
        mFirstCard.requestFocus();
        idle(0);
        mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_BACK));
        mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_BACK));

        // The panel mode stays on: the next card that keeps the focus brings the panel again
        mSecondCard.requestFocus();
        idle(0);
        assertEquals(View.VISIBLE, panel().getVisibility());
        assertTrue(UtubotSettings.instance(mActivity).isSummaryPanelEnabled());
    }

    @Test
    public void focusOnTheSidebarHidesThePanel() {
        resume();
        mFirstCard.requestFocus();
        idle(DELAY_MS + 100);

        mSidebar.requestFocus();
        idle(0);

        assertEquals(View.GONE, panel().getVisibility());
    }

    @Test
    public void aCardThatLeavesTheScreenHidesThePanel() {
        resume();
        mFirstCard.requestFocus();
        idle(DELAY_MS + 100);
        assertEquals(View.VISIBLE, panel().getVisibility());

        mCards.removeView(mFirstCard);
        idle(0);

        assertEquals(View.GONE, panel().getVisibility());
    }

    @Test
    public void thePanelGoesWhenTheScreenPauses() {
        resume();
        mFirstCard.requestFocus();
        idle(DELAY_MS + 100);

        mController.onPause();

        assertEquals(View.GONE, panel().getVisibility());
    }

    @Test
    public void turningThePanelModeOffHidesIt() {
        resume();
        mFirstCard.requestFocus();
        idle(DELAY_MS + 100);

        UtubotSettings.instance(mActivity).setSummaryPanelEnabled(false);
        idle(0);

        assertEquals(View.GONE, panel().getVisibility());
    }

    @Test
    public void theInfoKeyOpensTheSummaryViewAndBackClosesItWithTheFocusOnTheSameCard() {
        resume();
        mSecondCard.requestFocus();
        idle(DELAY_MS + 100);
        assertEquals(View.VISIBLE, panel().getVisibility());

        assertTrue(mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_INFO)));
        mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_INFO));
        idle(0);

        assertEquals("the panel stays out of the view's way", View.GONE, panel().getVisibility());

        assertTrue(mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_BACK)));
        mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_BACK));
        idle(0);

        assertSame(mSecondCard, focus());
    }

    @Test
    public void thePanelComesBackForTheCardAfterTheSummaryViewClosed() {
        resume();
        mSecondCard.requestFocus();
        idle(DELAY_MS + 100);
        mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_INFO));
        mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_INFO));
        idle(0);

        mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_BACK));
        mController.dispatchKeyEvent(up(KeyEvent.KEYCODE_BACK));
        idle(DELAY_MS + 100);

        assertEquals(View.VISIBLE, panel().getVisibility());
        assertSame(mSecondCard, focus());
    }

    @Test
    public void theInfoKeyOnTheSidebarDoesNothing() {
        resume();
        mSidebar.requestFocus();
        idle(0);

        assertFalse(mController.dispatchKeyEvent(down(KeyEvent.KEYCODE_INFO)));
    }

    @Test
    public void theLooperIsTheMainOne() {
        assertEquals(Looper.getMainLooper(), Looper.myLooper());
    }
}
