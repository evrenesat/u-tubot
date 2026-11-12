package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;
import android.view.KeyEvent;
import android.widget.ScrollView;

import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * A focusable text area for a TV remote: Up and Down scroll it by a readable page, and Up at the top lets the focus go on (to Retry)
 */
public class UtubotPageScrollView extends ScrollView {
    private static final int PERCENT = 100;
    private final int mPagePercent;

    public UtubotPageScrollView(Context context) {
        super(context);
        mPagePercent = getResources().getInteger(R.integer.utubot_overlay_scroll_page_percent);
        setFocusable(true);
        setFocusableInTouchMode(false);
        setVerticalScrollBarEnabled(true);
        setScrollbarFadingEnabled(false);
        setSmoothScrollingEnabled(true);
        setBackgroundResource(R.drawable.utubot_focus_background);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        int key = event.getKeyCode();

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
