package com.liskovsoft.smartyoutubetv2.tv.utubot.films;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.bumptech.glide.Glide;

/**
 * The look of the film screens, taken from the YouTube home of the app: the dark background of the grey scheme, the white focus ring with
 * a slight zoom of the focused card, titles under the cards and the system font.
 */
final class FilmsUi {
    static final int BACKGROUND = 0xFF181818;
    static final int TEXT = Color.WHITE;
    static final int TEXT_DIM = 0xFFB0B0B0;
    static final int CARD = 0xFF282828;
    static final int CHIP = 0xFF343434;
    static final int FOCUS = Color.WHITE;
    static final int WARN = 0xFFFFAA3F;
    static final int ACCENT = 0xFF2F6FB0;
    static final int ROW_HEADER_SP = 20;
    static final int TITLE_SP = 14;
    static final int BODY_SP = 16;
    static final int CHIP_SP = 12;
    static final int POSTER_W = 110;
    static final int POSTER_H = 165;
    static final int MARGIN = 48;
    static final int GAP = 12;
    private static final int FOCUS_STROKE = 3;
    private static final int CORNER = 6;
    private static final float FOCUS_SCALE = 1.08f;

    private FilmsUi() {
    }

    static int dp(Context context, float value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    static TextView text(Context context, String text, int sp, int color, boolean bold) {
        TextView view = new TextView(context);
        view.setText(text);
        view.setTextSize(sp);
        view.setTextColor(color);

        if (bold) {
            view.setTypeface(Typeface.DEFAULT_BOLD);
        }

        return view;
    }

    static TextView rowHeader(Context context, String text) {
        TextView view = text(context, text, ROW_HEADER_SP, TEXT, false);
        view.setPadding(dp(context, MARGIN), dp(context, 20), dp(context, MARGIN), dp(context, 8));

        return view;
    }

    static GradientDrawable rounded(Context context, int fill, int strokeColor, int strokeDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(context, CORNER));
        drawable.setStroke(dp(context, strokeDp), strokeColor);

        return drawable;
    }

    /**
     * Gives a view the focus look of the app: the white ring around the box and a slight zoom.
     */
    static void focusRing(View focusable, View box, int fill, @Nullable Runnable onChange) {
        Context context = focusable.getContext();
        GradientDrawable normal = rounded(context, fill, Color.TRANSPARENT, FOCUS_STROKE);
        GradientDrawable focused = rounded(context, fill, FOCUS, FOCUS_STROKE);
        GradientDrawable ring = rounded(context, Color.TRANSPARENT, FOCUS, FOCUS_STROKE);
        boolean overlay = box instanceof FrameLayout;
        box.setBackground(overlay ? rounded(context, fill, Color.TRANSPARENT, FOCUS_STROKE) : normal);
        focusable.setFocusable(true);
        focusable.setClickable(true);
        focusable.setFocusableInTouchMode(true);
        focusable.setOnFocusChangeListener((view, hasFocus) -> {
            if (overlay) {
                box.setForeground(hasFocus ? ring : null); // the picture covers a background, so the ring is drawn over it
            } else {
                box.setBackground(hasFocus ? focused : normal);
            }

            view.animate().scaleX(hasFocus ? FOCUS_SCALE : 1f).scaleY(hasFocus ? FOCUS_SCALE : 1f).setDuration(120).start();

            if (hasFocus && onChange != null) {
                onChange.run();
            }
        });
    }

    /**
     * A poster with the title under it, a watched tick and a progress bar.
     *
     * @param share 0 for none, otherwise how far the owner has watched
     */
    static View posterCard(Context context, String title, String subtitle, @Nullable String posterUrl, float share, boolean watched,
                           View.OnClickListener onClick) {
        LinearLayout card = new LinearLayout(context);
        card.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(context, 6);
        card.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(dp(context, POSTER_W) + 2 * pad, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.setMargins(dp(context, 4), dp(context, 18), dp(context, 4), dp(context, 18));
        card.setLayoutParams(cardParams);

        FrameLayout frame = new FrameLayout(context);
        ImageView poster = new ImageView(context);
        poster.setScaleType(ImageView.ScaleType.CENTER_CROP);
        frame.addView(poster, new FrameLayout.LayoutParams(dp(context, POSTER_W), dp(context, POSTER_H)));

        if (posterUrl != null && !posterUrl.isEmpty()) {
            Glide.with(context.getApplicationContext()).load(posterUrl).into(poster);
        }

        if (watched) {
            TextView tick = text(context, "✓", 14, Color.BLACK, true);
            tick.setGravity(Gravity.CENTER);
            tick.setBackground(rounded(context, WARN, Color.TRANSPARENT, 0));
            FrameLayout.LayoutParams tickParams = new FrameLayout.LayoutParams(dp(context, 24), dp(context, 24), Gravity.TOP | Gravity.END);
            tickParams.setMargins(0, dp(context, 6), dp(context, 6), 0);
            frame.addView(tick, tickParams);
        }

        if (share > 0 && !watched) {
            View bar = new View(context);
            bar.setBackgroundColor(WARN);
            frame.addView(bar, new FrameLayout.LayoutParams(Math.round(dp(context, POSTER_W) * share), dp(context, 4), Gravity.BOTTOM | Gravity.START));
        }

        card.addView(frame, new LinearLayout.LayoutParams(dp(context, POSTER_W), dp(context, POSTER_H)));

        TextView name = text(context, title, TITLE_SP, TEXT, false);
        name.setMaxLines(2);
        name.setEllipsize(TextUtils.TruncateAt.END);
        name.setPadding(0, dp(context, 6), 0, 0);
        card.addView(name);

        if (subtitle != null && !subtitle.isEmpty()) {
            TextView sub = text(context, subtitle, CHIP_SP, TEXT_DIM, false);
            sub.setSingleLine();
            card.addView(sub);
        }

        focusRing(card, frame, CARD, null);
        card.setOnClickListener(onClick);

        return card;
    }

    static TextView chip(Context context, String text, boolean warn) {
        TextView chip = text(context, text, CHIP_SP, warn ? Color.BLACK : TEXT, false);
        chip.setPadding(dp(context, 8), dp(context, 3), dp(context, 8), dp(context, 3));
        chip.setBackground(rounded(context, warn ? WARN : CHIP, Color.TRANSPARENT, 0));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, 0, dp(context, 6), 0);
        chip.setLayoutParams(params);

        return chip;
    }

    /** A focusable button: the fill is the accent colour, the ring shows the focus */
    static TextView button(Context context, String label, int sp, View.OnClickListener onClick) {
        TextView button = text(context, label, sp, TEXT, true);
        button.setGravity(Gravity.CENTER);
        button.setPadding(dp(context, 28), dp(context, 12), dp(context, 28), dp(context, 12));
        focusRing(button, button, ACCENT, null);
        button.setOnClickListener(onClick);

        return button;
    }

    static String clock(long millis) {
        long seconds = millis / 1000;
        long hours = seconds / 3600;
        long minutes = seconds % 3600 / 60;

        return hours > 0 ? String.format(java.util.Locale.US, "%d:%02d:%02d", hours, minutes, seconds % 60)
                : String.format(java.util.Locale.US, "%d:%02d", minutes, seconds % 60);
    }
}
