package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotBusyTracker;
import com.liskovsoft.smartyoutubetv2.tv.R;

import java.lang.ref.WeakReference;

/**
 * The tiny badge at the top right of a screen: the working dots (and the number of requests when there are several) while
 * any u-tubot request is in flight. It shows only after the work lasted a moment and stays a moment, so quick requests don't flicker.
 * <p>
 * It is the value of a WeakHashMap keyed by its activity (see UtubotAppHooks), so it must not hold the activity, or a view of it (a view
 * holds its context), strongly: the entry would keep its own key alive. The activity's view tree holds the badge.
 */
class UtubotBadgeController {
    private final WeakReference<Activity> mActivity;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final UtubotBusyTracker mTracker = UtubotBusyTracker.instance();
    private final long mShowDelayMs;
    private final long mMinVisibleMs;
    private WeakReference<UtubotBadgeView> mBadge = new WeakReference<>(null);
    private final Runnable mShow = this::show;
    private final Runnable mHide = this::hide;
    private final UtubotBusyTracker.Listener mListener = count -> mHandler.post(this::onCountChanged);
    private long mShownAtMs;
    private boolean mIsAttached;

    UtubotBadgeController(Activity activity) {
        mActivity = new WeakReference<>(activity);
        mShowDelayMs = activity.getResources().getInteger(R.integer.utubot_busy_show_delay_ms);
        mMinVisibleMs = activity.getResources().getInteger(R.integer.utubot_busy_min_visible_ms);
    }

    void onResume() {
        Activity activity = mActivity.get();
        ViewGroup content = activity != null ? activity.findViewById(android.R.id.content) : null;

        if (content == null) {
            return;
        }

        UtubotBadgeView badge = mBadge.get();

        if (badge == null) {
            badge = new UtubotBadgeView(activity);
            mBadge = new WeakReference<>(badge);
        }

        if (badge.getParent() != content) {
            if (badge.getParent() instanceof ViewGroup) {
                ((ViewGroup) badge.getParent()).removeView(badge);
            }

            int margin = activity.getResources().getDimensionPixelSize(R.dimen.utubot_badge_margin);
            FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.TOP | Gravity.END);
            params.setMargins(margin, margin, margin, margin);
            content.addView(badge, params);
        }

        mIsAttached = true;
        mTracker.addListener(mListener);
        onCountChanged();
    }

    void onPause() {
        mIsAttached = false;
        mTracker.removeListener(mListener);
        mHandler.removeCallbacksAndMessages(null);
        hide();
    }

    void onDestroy() {
        onPause();
        UtubotBadgeView badge = mBadge.get();

        if (badge != null && badge.getParent() instanceof ViewGroup) {
            ((ViewGroup) badge.getParent()).removeView(badge);
        }
    }

    private void onCountChanged() {
        if (!mIsAttached) {
            return;
        }

        UtubotBadgeView badge = mBadge.get();

        if (badge == null) {
            return;
        }

        int count = mTracker.getCount();

        if (count > 0) {
            mHandler.removeCallbacks(mHide);
            badge.setCountText(count);

            if (badge.getVisibility() != View.VISIBLE) {
                mHandler.removeCallbacks(mShow);
                mHandler.postDelayed(mShow, mShowDelayMs);
            }
        } else {
            mHandler.removeCallbacks(mShow);

            if (badge.getVisibility() == View.VISIBLE) {
                long visibleMs = SystemClock.uptimeMillis() - mShownAtMs;
                mHandler.removeCallbacks(mHide);
                mHandler.postDelayed(mHide, Math.max(0, mMinVisibleMs - visibleMs));
            }
        }
    }

    private void show() {
        UtubotBadgeView badge = mBadge.get();

        if (badge != null && mIsAttached && mTracker.isBusy()) {
            mShownAtMs = SystemClock.uptimeMillis();
            badge.setCount(mTracker.getCount());
        }
    }

    private void hide() {
        UtubotBadgeView badge = mBadge.get();

        if (badge != null) {
            badge.setCount(0);
        }
    }

    /**
     * The dots and, with several requests, their number
     */
    static final class UtubotBadgeView extends LinearLayout {
        private final UtubotWorkingIndicator mIndicator;
        private final TextView mCount;

        UtubotBadgeView(Activity activity) {
            super(activity);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            setBackgroundResource(R.drawable.utubot_badge_background);
            int padding = getResources().getDimensionPixelSize(R.dimen.utubot_badge_padding);
            setPadding(padding, padding, padding, padding);
            setFocusable(false);
            setClickable(false);
            setVisibility(GONE);
            setContentDescription(activity.getString(R.string.utubot_busy_badge));

            mIndicator = new UtubotWorkingIndicator(activity);
            addView(mIndicator);

            mCount = new TextView(activity);
            mCount.setTextColor(getResources().getColor(R.color.utubot_panel_title));
            mCount.setTextSize(android.util.TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.utubot_badge_count_size));
            mCount.setVisibility(GONE);
            LayoutParams countParams = new LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
            countParams.leftMargin = padding;
            addView(mCount, countParams);
        }

        /**
         * Updates the number while shown, without showing
         */
        void setCountText(int count) {
            if (getVisibility() == VISIBLE) {
                setCount(count);
            }
        }

        /**
         * @param count 0 hides the badge
         */
        void setCount(int count) {
            boolean isBusy = count > 0;
            setVisibility(isBusy ? VISIBLE : GONE);
            mIndicator.setActive(isBusy);
            mCount.setVisibility(count > 1 ? VISIBLE : GONE);
            mCount.setText(String.valueOf(count));
        }
    }
}
