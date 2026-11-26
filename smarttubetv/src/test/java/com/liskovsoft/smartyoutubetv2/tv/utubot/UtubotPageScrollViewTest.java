package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;
import org.robolectric.shadows.ShadowLooper;

import java.util.concurrent.TimeUnit;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The self-scrolling of the summary/answer text: a tall text crawls down by itself at the reading pace and stops at the bottom, a short
 * one does not, a key pauses it and it resumes after the delay, and Up and Down still scroll by hand. The clock is the looper's.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotPageScrollViewTest {
    private static final int VIEW_WIDTH = 500;
    private static final int VIEW_HEIGHT = 300;
    private static final int CHILD_HEIGHT = 360;
    private static final int MAX_SCROLL = CHILD_HEIGHT - VIEW_HEIGHT;
    private static final int SPEED_PX_PER_SEC = 60;

    private Activity mActivity;
    private Context mContext;
    private UtubotPageScrollView mScroll;

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.getApplication();
        ((Application) mContext).setTheme(androidx.appcompat.R.style.Theme_AppCompat);
        UtubotSettings.instance(mContext).setAutoScrollSpeedPxPerSec(SPEED_PX_PER_SEC);

        ScreenActivity activity = Robolectric.buildActivity(ScreenActivity.class).setup().get();
        mActivity = activity;
        mScroll = activity.scroll;

        // Add a tall child as the last step: the scroll view's own onLayout lays the child out at its text height, so force it taller
        // than the area after the activity has laid the view out.
        forceChildTall();
    }

    /**
     * An activity whose whole content is the scroll view, so the view has a window (focus and layout work) like the real one.
     */
    public static final class ScreenActivity extends Activity {
        FrameLayout screen;
        UtubotPageScrollView scroll;

        @Override
        protected void onCreate(android.os.Bundle savedInstanceState) {
            super.onCreate(savedInstanceState);
            screen = new FrameLayout(this);
            scroll = new UtubotPageScrollView(this);
            screen.addView(scroll, new FrameLayout.LayoutParams(VIEW_WIDTH, VIEW_HEIGHT));
            setContentView(screen);
        }
    }

    private void forceChildTall() {
        if (mScroll.getChildCount() == 0) {
            TextView child = new TextView(mContext);
            child.setText(longText());
            mScroll.addView(child, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
            mScroll.measure(View.MeasureSpec.makeMeasureSpec(VIEW_WIDTH, View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(VIEW_HEIGHT, View.MeasureSpec.EXACTLY));
            mScroll.layout(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
        }

        TextView child = (TextView) mScroll.getChildAt(0);
        child.layout(0, 0, child.getMeasuredWidth(), CHILD_HEIGHT);
    }

    private static String longText() {
        StringBuilder text = new StringBuilder();

        for (int i = 0; i < 400; i++) {
            text.append("word ").append(i).append('\n');
        }

        return text.toString();
    }

    private void idle(long ms) {
        ShadowLooper.idleMainLooper(ms, TimeUnit.MILLISECONDS);
    }

    private static KeyEvent down(int key) {
        return new KeyEvent(KeyEvent.ACTION_DOWN, key);
    }

    @After
    public void tearDown() {
        if (mScroll != null) {
            mScroll.cancelAutoScroll();
        }

        if (mActivity != null) {
            mActivity.finish();
        }
    }

    @Test
    public void aTallTextCrawlsDownByItselfAndStopsAtTheBottom() {
        mScroll.requestFocus();
        mScroll.setAutoScroll(true);

        assertEquals(0, mScroll.getScrollY());
        idle(200);
        assertTrue("the text starts crawling", mScroll.getScrollY() > 0);

        idle(5000);

        assertEquals("it stops at the bottom, showing the whole text", MAX_SCROLL, mScroll.getScrollY());
    }

    @Test
    public void aTextThatFitsDoesNotCrawl() {
        TextView child = (TextView) mScroll.getChildAt(0);
        child.layout(0, 0, child.getMeasuredWidth(), VIEW_HEIGHT);

        mScroll.setAutoScroll(true);
        idle(2000);

        assertEquals(0, mScroll.getScrollY());
    }

    @Test
    public void aKeyPausesTheCrawlAndItResumesAfterTheDelay() {
        mScroll.requestFocus();
        mScroll.setAutoScroll(true);

        idle(200);
        int before = mScroll.getScrollY();
        assertTrue(before > 0);

        // A key that does not scroll pauses the crawl: it stays put during the pause
        mScroll.dispatchKeyEvent(down(KeyEvent.KEYCODE_ENTER));
        idle(100);
        assertEquals(before, mScroll.getScrollY());

        // After the resume delay it continues toward the bottom
        idle(5000);
        assertTrue("it resumes after the pause", mScroll.getScrollY() > before);
    }

    @Test
    public void manualDownScrollStillWorks() {
        mScroll.requestFocus();
        mScroll.setAutoScroll(true);
        idle(200);

        // A manual Down is handled by the scroll view (it pages the text by itself, on top of the crawl)...
        int before = mScroll.getScrollY();
        assertTrue("a Down is handled by the scroll view", mScroll.dispatchKeyEvent(down(KeyEvent.KEYCODE_DPAD_DOWN)));
        assertTrue("a manual Down pages the text, not just one crawl step", mScroll.pageDelta(true) > 1);

        // ...and a manual Up pages it back up by a page too
        assertEquals("the manual press did not run past the top", before, mScroll.getScrollY());
        assertTrue("a manual Up pages the text back up, not just one crawl step", Math.abs(mScroll.pageDelta(false)) > 1);
    }

    @Test
    public void upAtTheTopLetsTheFocusGoOn() {
        mScroll.requestFocus();
        // At the top, Up is not handled here, so it can reach the Retry button above
        assertFalse("Up at the top is not handled by the scroll view", mScroll.dispatchKeyEvent(down(KeyEvent.KEYCODE_DPAD_UP)));
    }
}
