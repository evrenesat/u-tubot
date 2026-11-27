package com.liskovsoft.smartyoutubetv2.tv.utubot.films;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.Outline;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.bumptech.glide.Glide;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmDevice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient.Stream;

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
    static final int TITLE_SP = 16;
    static final int BODY_SP = 16;
    static final int CHIP_SP = 14;
    static final int POSTER_W = 96;
    static final int POSTER_H = 144;
    static final int CARD_W = 132;
    private static final int CARD_PAD = 4;
    static final int PLACEHOLDER_CARDS = 8;
    static final int PLACEHOLDER_ROWS = 3;
    static final int PLACEHOLDER = 0xFF222222;
    static final int PANEL = 0xD9000000;
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
        view.setPadding(dp(context, MARGIN), dp(context, 10), dp(context, MARGIN), dp(context, 2));

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
     * Gives a view the focus look of the app: the white ring around the box and a slight zoom of the whole box.
     */
    static void focusRing(View focusable, View box, int fill, @Nullable Runnable onChange) {
        focusRing(focusable, box, fill, focusable, onChange);
    }

    /**
     * The white ring around the box; {@code zoom} is the view that grows slightly on focus, or null for a ring only.
     */
    static void focusRing(View focusable, View box, int fill, @Nullable View zoom, @Nullable Runnable onChange) {
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

            if (zoom != null) {
                zoom.animate().scaleX(hasFocus ? FOCUS_SCALE : 1f).scaleY(hasFocus ? FOCUS_SCALE : 1f).setDuration(120).start();
            }

            if (hasFocus && onChange != null) {
                onChange.run();
            }
        });
    }

    /** Clips a view's content (a picture) to the rounded corners of the focus ring */
    static void clipRounded(View view) {
        float radius = dp(view.getContext(), CORNER);
        view.setOutlineProvider(new ViewOutlineProvider() {
            @Override
            public void getOutline(View v, Outline outline) {
                outline.setRoundRect(0, 0, v.getWidth(), v.getHeight(), radius);
            }
        });
        view.setClipToOutline(true);
    }

    /** A line of chips that wraps to the next line when the width is used up */
    static final class ChipFlow extends ViewGroup {
        ChipFlow(Context context) {
            super(context);
        }

        @Override
        protected void onMeasure(int widthSpec, int heightSpec) {
            int maxWidth = MeasureSpec.getSize(widthSpec) - getPaddingLeft() - getPaddingRight();
            int x = 0;
            int y = 0;
            int lineHeight = 0;
            int used = 0;

            for (int i = 0; i < getChildCount(); i++) {
                View child = getChildAt(i);
                measureChildWithMargins(child, widthSpec, 0, heightSpec, 0);
                MarginLayoutParams params = (MarginLayoutParams) child.getLayoutParams();
                int width = child.getMeasuredWidth() + params.leftMargin + params.rightMargin;
                int height = child.getMeasuredHeight() + params.topMargin + params.bottomMargin;

                if (x > 0 && x + width > maxWidth) {
                    x = 0;
                    y += lineHeight;
                    lineHeight = 0;
                }

                x += width;
                used = Math.max(used, x);
                lineHeight = Math.max(lineHeight, height);
            }

            setMeasuredDimension(resolveSize(used + getPaddingLeft() + getPaddingRight(), widthSpec),
                    resolveSize(y + lineHeight + getPaddingTop() + getPaddingBottom(), heightSpec));
        }

        @Override
        protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
            int maxWidth = right - left - getPaddingLeft() - getPaddingRight();
            int x = 0;
            int y = 0;
            int lineHeight = 0;

            for (int i = 0; i < getChildCount(); i++) {
                View child = getChildAt(i);
                MarginLayoutParams params = (MarginLayoutParams) child.getLayoutParams();
                int width = child.getMeasuredWidth() + params.leftMargin + params.rightMargin;
                int height = child.getMeasuredHeight() + params.topMargin + params.bottomMargin;

                if (x > 0 && x + width > maxWidth) {
                    x = 0;
                    y += lineHeight;
                    lineHeight = 0;
                }

                int childLeft = getPaddingLeft() + x + params.leftMargin;
                int childTop = getPaddingTop() + y + params.topMargin;
                child.layout(childLeft, childTop, childLeft + child.getMeasuredWidth(), childTop + child.getMeasuredHeight());
                x += width;
                lineHeight = Math.max(lineHeight, height);
            }
        }

        @Override
        protected LayoutParams generateDefaultLayoutParams() {
            return new MarginLayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        }

        @Override
        protected LayoutParams generateLayoutParams(LayoutParams params) {
            return new MarginLayoutParams(params);
        }

        @Override
        public LayoutParams generateLayoutParams(android.util.AttributeSet attrs) {
            return new MarginLayoutParams(getContext(), attrs);
        }

        @Override
        protected boolean checkLayoutParams(LayoutParams params) {
            return params instanceof MarginLayoutParams;
        }
    }

    /**
     * One stream as a row of chips on the card background: Best, quality, format, size and, in amber, a note for what this TV cannot show well.
     * The row is focusable, full width, and shows the focus as a ring only (no zoom, so no row is clipped at an edge).
     */
    static View streamRow(Context context, Stream stream, boolean best, UtubotFilmDevice device, View.OnClickListener onClick) {
        ChipFlow flow = new ChipFlow(context);
        int pad = dp(context, 10);
        flow.setPadding(pad, pad - dp(context, 3), pad, pad - dp(context, 3));

        if (best) {
            TextView bestChip = chip(context, "Best", false);
            bestChip.setBackground(rounded(context, ACCENT, Color.TRANSPARENT, 0));
            flow.addView(bestChip);
        }

        if (stream.resolution > 0) {
            TextView quality = chip(context, stream.resolution == 2160 ? "4K" : stream.resolution + "p", false);
            quality.setTypeface(Typeface.DEFAULT_BOLD);
            flow.addView(quality);
        }

        for (String label : stream.format.chips()) {
            flow.addView(chip(context, label, false));
        }

        if (stream.sizeBytes > 0) {
            flow.addView(chip(context, Stream.formatSize(stream.sizeBytes), false));
        }

        String note = stream.format.note(device);

        if (!note.isEmpty()) {
            flow.addView(chip(context, note, true));
        }

        if (flow.getChildCount() == 0) {
            flow.addView(chip(context, stream.display(), false));
        }

        ViewGroup.MarginLayoutParams params = new ViewGroup.MarginLayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, dp(context, 3), 0, dp(context, 3));
        flow.setLayoutParams(params);
        focusRing(flow, flow, CARD, null, null);
        flow.setOnClickListener(onClick);

        return flow;
    }

    /** A grey card-shaped block that stands in for a poster while the list loads */
    static View placeholderCard(Context context) {
        LinearLayout card = new LinearLayout(context);
        card.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(context, CARD_PAD);
        card.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(dp(context, CARD_W) + 2 * pad, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.setMargins(dp(context, 4), dp(context, 4), dp(context, 4), dp(context, 4));
        card.setLayoutParams(cardParams);

        View frame = new View(context);
        frame.setBackground(rounded(context, PLACEHOLDER, Color.TRANSPARENT, 0));
        card.addView(frame, new LinearLayout.LayoutParams(dp(context, POSTER_W), dp(context, POSTER_H)));
        card.addView(placeholderBar(context, POSTER_W - 10, 14, 8));
        card.addView(placeholderBar(context, POSTER_W / 2, 12, 4));

        return card;
    }

    static View placeholderBar(Context context, int widthDp, int heightDp, int topDp) {
        View bar = new View(context);
        bar.setBackground(rounded(context, PLACEHOLDER, Color.TRANSPARENT, 0));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(context, widthDp), dp(context, heightDp));
        params.topMargin = dp(context, topDp);
        bar.setLayoutParams(params);

        return bar;
    }

    /** Plain words for a failure and a focusable Retry button; the exception text stays in the log */
    static View errorBlock(Context context, String message, View.OnClickListener onRetry) {
        LinearLayout block = new LinearLayout(context);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, dp(context, 8), 0, dp(context, 8));
        block.setClipChildren(false);
        block.setClipToPadding(false);
        block.addView(text(context, message, BODY_SP, TEXT, false));
        TextView retry = button(context, "Retry", BODY_SP, onRetry);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(context, 10);
        block.addView(retry, params);

        return block;
    }

    /** The Retry button of {@link #errorBlock} */
    static View retryButton(View errorBlock) {
        return ((ViewGroup) errorBlock).getChildAt(1);
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
        card.setClipChildren(false);
        card.setClipToPadding(false); // the zoomed poster grows into the padding
        int pad = dp(context, CARD_PAD);
        card.setPadding(pad, pad, pad, pad);
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(dp(context, CARD_W) + 2 * pad, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.setMargins(dp(context, 4), dp(context, 4), dp(context, 4), dp(context, 4));
        card.setLayoutParams(cardParams);

        FrameLayout frame = new FrameLayout(context);
        ImageView poster = new ImageView(context);
        poster.setScaleType(ImageView.ScaleType.CENTER_CROP);
        frame.addView(poster, new FrameLayout.LayoutParams(dp(context, POSTER_W), dp(context, POSTER_H)));

        if (posterUrl != null && !posterUrl.isEmpty()) {
            Glide.with(context.getApplicationContext()).load(posterUrl).into(poster);
        }

        if (watched) {
            TextView tick = text(context, "\u2713", 14, TEXT, true);
            tick.setGravity(Gravity.CENTER);
            tick.setBackground(rounded(context, ACCENT, Color.TRANSPARENT, 0));
            FrameLayout.LayoutParams tickParams = new FrameLayout.LayoutParams(dp(context, 24), dp(context, 24), Gravity.TOP | Gravity.END);
            tickParams.setMargins(0, dp(context, 6), dp(context, 6), 0);
            frame.addView(tick, tickParams);
        }

        if (share > 0 && !watched) {
            View bar = new View(context);
            bar.setBackgroundColor(TEXT);
            frame.addView(bar, new FrameLayout.LayoutParams(Math.round(dp(context, POSTER_W) * share), dp(context, 4), Gravity.BOTTOM | Gravity.START));
        }

        clipRounded(frame);
        card.addView(frame, new LinearLayout.LayoutParams(dp(context, POSTER_W), dp(context, POSTER_H)));

        TextView name = text(context, title, TITLE_SP, TEXT, false);
        name.setSingleLine();
        name.setEllipsize(TextUtils.TruncateAt.END);
        name.setPadding(0, dp(context, 6), 0, 0);
        card.addView(name);

        if (subtitle != null && !subtitle.isEmpty()) {
            TextView sub = text(context, subtitle, CHIP_SP, TEXT_DIM, false);
            sub.setSingleLine();
            sub.setEllipsize(TextUtils.TruncateAt.END);
            card.addView(sub);
        }

        focusRing(card, frame, CARD, frame, null);
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
