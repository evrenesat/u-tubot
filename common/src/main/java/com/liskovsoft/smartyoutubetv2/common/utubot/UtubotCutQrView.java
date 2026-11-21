package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;
import android.content.ContextWrapper;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utils.QrCodeEncoder;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;

/**
 * The "Describe on phone…" sheet over the playing video: the waiting request's short address as a QR code, the address in text under
 * it. Nothing is paused: the video keeps playing behind the sheet. Back takes it away; the volume keys stay with the system.
 */
public final class UtubotCutQrView extends FrameLayout {
    private static final int SCRIM = 0xD0000000;
    private static final int TEXT = 0xFFFFFFFF;
    private static final int TITLE_TEXT_SIZE_SP = 20;
    private static final int HINT_TEXT_SIZE_SP = 16;
    private static final int PADDING_PX = 48;

    private UtubotCutQrView(Context context) {
        super(context);
    }

    /**
     * Puts the sheet over the activity's content; the video is not touched. Not an activity context: the address is said instead.
     */
    public static void show(Context context, String url, String hint) {
        Activity activity = activityOf(context);

        if (activity == null) {
            MessageHelpers.showLongMessage(context, url);
            return;
        }

        ViewGroup content = activity.findViewById(android.R.id.content);
        close(content);
        content.addView(new UtubotCutQrView(activity).build(url, hint),
                new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private static void close(ViewGroup content) {
        for (int i = content.getChildCount() - 1; i >= 0; i--) {
            if (content.getChildAt(i) instanceof UtubotCutQrView) {
                content.removeViewAt(i);
            }
        }
    }

    private UtubotCutQrView build(String url, String hint) {
        setBackgroundColor(SCRIM);
        setClickable(true);
        setFocusable(true);
        setFocusableInTouchMode(true);
        setOnKeyListener((view, keyCode, event) -> {
            switch (keyCode) {
                case KeyEvent.KEYCODE_VOLUME_UP:
                case KeyEvent.KEYCODE_VOLUME_DOWN:
                case KeyEvent.KEYCODE_VOLUME_MUTE:
                    return false; // the volume keys stay with the system: on a TV without CEC volume this is the only way to change it
            }

            if (event.getAction() != KeyEvent.ACTION_DOWN) {
                return true; // the rest of every press is this sheet's too
            }

            if (keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_ESCAPE) {
                detach();
                return true;
            }

            return true; // nothing under the sheet moves while it is up
        });

        DisplayMetrics metrics = getResources().getDisplayMetrics();
        int sidePx = Math.min(metrics.widthPixels, metrics.heightPixels) * 3 / 5;
        int codePx = QrCodeEncoder.toBitmap(url, sidePx) != null ? sidePx : 0;

        LinearLayout column = new LinearLayout(getContext());
        column.setOrientation(LinearLayout.VERTICAL);
        column.setGravity(Gravity.CENTER_HORIZONTAL);
        column.setPadding(PADDING_PX, PADDING_PX, PADDING_PX, PADDING_PX);
        addView(column, new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));

        TextView address = new TextView(getContext());
        address.setText(url);
        address.setTextColor(TEXT);
        address.setTextSize(TITLE_TEXT_SIZE_SP);
        address.setTypeface(Typeface.DEFAULT_BOLD);
        address.setGravity(Gravity.CENTER);
        column.addView(address, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        if (codePx > 0) {
            Bitmap code = QrCodeEncoder.toBitmap(url, codePx);
            ImageView codeView = new ImageView(getContext());
            codeView.setImageBitmap(code);
            codeView.setBackgroundColor(Color.WHITE);
            int padding = codePx / 16;
            codeView.setPadding(padding, padding, padding, padding);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(codePx + padding * 2, codePx + padding * 2);
            params.topMargin = padding;
            params.bottomMargin = padding;
            column.addView(codeView, params);
        }

        TextView hintView = new TextView(getContext());
        hintView.setText(hint);
        hintView.setTextColor(TEXT);
        hintView.setTextSize(HINT_TEXT_SIZE_SP);
        hintView.setGravity(Gravity.CENTER);
        column.addView(hintView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // The sheet holds the focus, so its keys are its own; a key that arrives before the attach is asked for again
        post(this::requestFocus);

        return this;
    }

    private void detach() {
        if (getParent() instanceof ViewGroup) {
            ((ViewGroup) getParent()).removeView(this);
        }
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