package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;
import android.content.ContextWrapper;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import java.lang.ref.WeakReference;

/**
 * The small "Outside the cut" badge over the playing video. It never takes the focus and holds no key: the D-pad stays with the
 * player. It is gone as soon as the playback is back in a kept part.
 */
public final class UtubotCutBadge {
    private static final int BACKGROUND = 0xCC101418;
    private static final int TEXT_COLOR = 0xFFFFFFFF;
    private static final int TEXT_SIZE_SP = 14;
    private static final int PADDING_DP = 10;
    private static final int MARGIN_DP = 20;

    private final WeakReference<Activity> mActivity;
    private WeakReference<TextView> mView = new WeakReference<>(null);
    private String mText;

    private UtubotCutBadge(Activity activity) {
        mActivity = new WeakReference<>(activity);
    }

    /**
     * A badge for the activity behind the context, or null when there is none (no activity to show it over)
     */
    @Nullable
    public static UtubotCutBadge attach(Context context) {
        Activity activity = activityOf(context);

        return activity != null ? new UtubotCutBadge(activity) : null;
    }

    public void show(String text) {
        Activity activity = mActivity.get();

        if (activity == null) {
            return;
        }

        TextView view = mView.get();

        if (view == null || view.getParent() == null) {
            view = createView(activity);
            mView = new WeakReference<>(view);
            mText = null;
        }

        if (!text.equals(mText)) {
            view.setText(text);
            mText = text;
        }

        view.setVisibility(View.VISIBLE);
    }

    public void hide() {
        TextView view = mView.get();

        if (view != null) {
            view.setVisibility(View.GONE);
        }
    }

    public void destroy() {
        TextView view = mView.get();

        if (view != null && view.getParent() instanceof ViewGroup) {
            ((ViewGroup) view.getParent()).removeView(view);
        }

        mView = new WeakReference<>(null);
        mText = null;
    }

    private static TextView createView(Activity activity) {
        ViewGroup content = activity.findViewById(android.R.id.content);
        TextView view = new TextView(activity);
        view.setTextColor(TEXT_COLOR);
        view.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, TEXT_SIZE_SP);
        view.setGravity(Gravity.CENTER_VERTICAL);

        int padding = dp(activity, PADDING_DP);
        view.setPadding(padding, padding, padding, padding);

        GradientDrawable background = new GradientDrawable();
        background.setColor(BACKGROUND);
        background.setCornerRadius(dp(activity, 8));
        view.setBackground(background);

        view.setFocusable(false);
        view.setClickable(false);
        view.setVisibility(View.GONE);

        int margin = dp(activity, MARGIN_DP);
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.START);
        params.setMargins(margin, margin, margin, margin);
        content.addView(view, params);

        view.bringToFront();

        return view;
    }

    private static int dp(Context context, int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    @Nullable
    private static Activity activityOf(Context context) {
        Context current = context;

        while (current instanceof ContextWrapper && !(current instanceof Activity)) {
            current = ((ContextWrapper) current).getBaseContext();
        }

        return current instanceof Activity ? (Activity) current : null;
    }
}
