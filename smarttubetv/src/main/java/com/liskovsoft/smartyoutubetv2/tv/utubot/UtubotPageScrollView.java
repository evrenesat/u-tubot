package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewTreeObserver;
import android.widget.ScrollView;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotAutoScroll;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotScheduler;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * A focusable text area for a TV remote: Up and Down scroll it by a readable page, and Up at the top lets the focus go on (to Retry).
 * When the text is taller than the area it also scrolls slowly by itself at a reading pace, so waiting long enough shows it all; a key
 * pauses it and it resumes after a while, and manual Up and Down still scroll by hand.
 */
public class UtubotPageScrollView extends ScrollView {
    private static final int PERCENT = 100;
    private final int mPagePercent;
    private final UtubotAutoScroll mAutoScroll;
    private boolean mAutoScrollRequested;

    public UtubotPageScrollView(Context context) {
        super(context);
        mPagePercent = getResources().getInteger(R.integer.utubot_overlay_scroll_page_percent);
        setFocusable(true);
        setFocusableInTouchMode(false);
        setVerticalScrollBarEnabled(true);
        setScrollbarFadingEnabled(false);
        setSmoothScrollingEnabled(true);
        setBackgroundResource(R.drawable.utubot_focus_background);

        // The reading pace is read from the settings on every step, so a change applies at once.
        mAutoScroll = UtubotAutoScroll.of(UtubotScheduler.mainThread(),
                () -> UtubotSettings.instance(context).getAutoScrollSpeedPxPerSec(), ofScrollTarget());

        // The content height is known only after the first layout (and after the text changes), so re-read it whenever the layout settles.
        getViewTreeObserver().addOnGlobalLayoutListener(mAutoScrollLayout);
        addOnAttachStateChangeListener(new View.OnAttachStateChangeListener() {
            @Override
            public void onViewAttachedToWindow(View view) {
            }

            @Override
            public void onViewDetachedFromWindow(View view) {
                getViewTreeObserver().removeOnGlobalLayoutListener(mAutoScrollLayout);
                mAutoScroll.cancel();
            }
        });
    }

    /** The global layout listener, kept to remove it when the view leaves the window. */
    private final ViewTreeObserver.OnGlobalLayoutListener mAutoScrollLayout = this::evaluateAutoScroll;

    /**
     * Whether the text should crawl by itself when it is tall enough. Called when the view opens and again when its text is shown: a
     * short text never crawls, a tall one does until the bottom is reached.
     */
    void setAutoScroll(boolean requested) {
        mAutoScrollRequested = requested;
        evaluateAutoScroll();
    }

    /**
     * Stops the crawl and frees the timer: the view is going away (tests, or the view leaving the window).
     */
    public void cancelAutoScroll() {
        mAutoScrollRequested = false;
        mAutoScroll.cancel();
    }

    private void evaluateAutoScroll() {
        mAutoScroll.setEnabled(mAutoScrollRequested && maxScroll() > 0);
    }

    private UtubotAutoScroll.ScrollTarget ofScrollTarget() {
        return new UtubotAutoScroll.ScrollTarget() {
            @Override
            public int current() {
                return getScrollY();
            }

            @Override
            public int max() {
                return maxScroll();
            }

            @Override
            public void moveTo(int offset) {
                scrollTo(0, offset);
            }
        };
    }

    /**
     * How far the content goes past the area: zero when the content fits, so a short text never scrolls.
     */
    private int maxScroll() {
        if (getChildCount() == 0) {
            return 0;
        }

        int visible = getHeight() - getPaddingTop() - getPaddingBottom();

        return Math.max(0, getChildAt(0).getHeight() - visible);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        int key = event.getKeyCode();

        // Any key the view gets pauses the crawl and starts the resume delay again; the key goes on to the widget as before.
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            mAutoScroll.keyPressed();
        }

        if (!hasFocus() || (key != KeyEvent.KEYCODE_DPAD_DOWN && key != KeyEvent.KEYCODE_DPAD_UP)) {
            return super.dispatchKeyEvent(event);
        }

        if (key == KeyEvent.KEYCODE_DPAD_UP && getScrollY() <= 0) {
            return false;
        }

        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            smoothScrollBy(0, pageDelta(key == KeyEvent.KEYCODE_DPAD_DOWN));
        }

        return true;
    }

    /**
     * How far one press scrolls: a page less a few lines, down or up, never past the ends
     */
    int pageDelta(boolean isDown) {
        int page = Math.max(1, (getHeight() - getPaddingTop() - getPaddingBottom()) * mPagePercent / PERCENT);

        if (getChildCount() == 0) {
            return 0;
        }

        int maxScroll = Math.max(0, getChildAt(0).getHeight() - (getHeight() - getPaddingTop() - getPaddingBottom()));

        return isDown ? Math.min(page, maxScroll - getScrollY()) : -Math.min(page, getScrollY());
    }
}
