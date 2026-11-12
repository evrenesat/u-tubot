package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;
import android.graphics.Typeface;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.ForegroundColorSpan;
import android.text.style.StyleSpan;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelText;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotStateText;
import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * The passive Summary panel: a header (the prompt label, the working indicator and the hint to the Summary view), the title and a few
 * lines of the glance summary. It is a preview: it never takes the focus and never handles a key, so the grid below it keeps working.
 * The Summary view (UtubotSummaryOverlay) is where the user reads and picks prompts.
 */
public class UtubotPanelView extends LinearLayout {
    private final TextView mLabel;
    private final UtubotWorkingIndicator mIndicator;
    private final TextView mTitle;
    private final TextView mText;
    private final int mLeadColor;
    private final int mStatusColor;
    private final int mTextColor;

    public UtubotPanelView(Context context) {
        super(context);
        setOrientation(VERTICAL);
        setBackgroundColor(getResources().getColor(R.color.utubot_panel_background));
        int padding = getResources().getDimensionPixelSize(R.dimen.utubot_panel_padding);
        int gap = getResources().getDimensionPixelSize(R.dimen.utubot_panel_gap);
        setPadding(padding, padding, padding, padding);
        setVisibility(GONE);
        setFocusable(false);
        setFocusableInTouchMode(false);
        setClickable(false);
        setDescendantFocusability(FOCUS_BLOCK_DESCENDANTS);

        mLeadColor = getResources().getColor(R.color.utubot_panel_lead);
        mStatusColor = getResources().getColor(R.color.utubot_panel_status);
        mTextColor = getResources().getColor(R.color.utubot_panel_text);

        LinearLayout header = new LinearLayout(context);
        header.setOrientation(HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        mLabel = text(context, R.color.utubot_panel_label, R.dimen.utubot_panel_label_size);
        mLabel.setSingleLine(true);
        mLabel.setEllipsize(TextUtils.TruncateAt.END);
        header.addView(mLabel, new LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f));
        mIndicator = new UtubotWorkingIndicator(context);
        LayoutParams indicatorParams = new LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        indicatorParams.leftMargin = gap;
        header.addView(mIndicator, indicatorParams);
        addView(header, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));

        TextView hint = text(context, R.color.utubot_panel_hint, R.dimen.utubot_panel_hint_size);
        hint.setText(R.string.utubot_panel_hint);
        hint.setSingleLine(true);
        hint.setEllipsize(TextUtils.TruncateAt.END);
        addView(hint, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));

        mTitle = text(context, R.color.utubot_panel_title, R.dimen.utubot_panel_title_size);
        mTitle.setMaxLines(getResources().getInteger(R.integer.utubot_panel_title_lines));
        mTitle.setEllipsize(TextUtils.TruncateAt.END);
        addView(mTitle, below(gap));

        mText = text(context, R.color.utubot_panel_text, R.dimen.utubot_panel_text_size);
        mText.setMaxLines(getResources().getInteger(R.integer.utubot_panel_text_lines));
        mText.setEllipsize(TextUtils.TruncateAt.END);
        addView(mText, below(gap));
    }

    /**
     * The layout params of the panel inside an activity's content: a strip of the configured share of the width along the right edge
     * (the margin included), as high as its lines need, at the bottom and never above {@code topInsetPx} (the top bar of the screen).
     * It is a sibling of the screen's own views and takes only this corner: it never matches the parent in either direction.
     */
    public static FrameLayout.LayoutParams layoutParams(Context context, int parentWidthPx, int topInsetPx) {
        int percent = context.getResources().getInteger(R.integer.utubot_panel_width_percent);
        int margin = context.getResources().getDimensionPixelSize(R.dimen.utubot_panel_margin);
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(Math.max(0, parentWidthPx * percent / PERCENT - margin),
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM | Gravity.END);
        params.setMargins(margin, Math.max(0, topInsetPx) + margin, margin, margin);

        return params;
    }

    private static final int PERCENT = 100;

    public void bind(State state) {
        mLabel.setText(state.promptLabel != null ? state.promptLabel : getContext().getString(R.string.utubot_title));
        mTitle.setText(state.video != null ? state.video.getTitle() : "");
        mIndicator.setActive(state.isWorking());

        switch (state.phase) {
            case WAITING:
                showStatus(R.string.utubot_panel_waiting);
                break;
            case LOADING:
                showStatus(R.string.utubot_panel_loading);
                break;
            case PENDING:
                showStatus(R.string.utubot_panel_pending);
                break;
            case NEEDS_TRANSCRIPT:
                showStatus(UtubotStateText.noCaptionsShort(getContext(), state));
                break;
            case DELAYED:
                showStatus(UtubotStateText.delayed(getContext(), state));
                break;
            case TRANSCRIBING:
                showStatus(UtubotStateText.transcribing(getContext(), state));
                break;
            case READY:
                mText.setText(state.text != null && !state.text.isEmpty() ? styled(state.text) : getContext().getString(R.string.utubot_panel_empty));
                mText.setTextColor(mTextColor);
                break;
            case FAILED:
                mText.setText(getContext().getString(R.string.utubot_panel_failed, state.error != null ? state.error : "-"));
                mText.setTextColor(mStatusColor);
                break;
            default:
                mText.setText("");
        }
    }

    /**
     * The summary, with the "→ " answer line brighter and bold
     */
    CharSequence styled(@Nullable String text) {
        UtubotPanelText.Split split = UtubotPanelText.split(text);

        if (split.lead == null) {
            return split.rest;
        }

        SpannableStringBuilder builder = new SpannableStringBuilder(split.lead);
        builder.setSpan(new StyleSpan(Typeface.BOLD), 0, split.lead.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        builder.setSpan(new ForegroundColorSpan(mLeadColor), 0, split.lead.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);

        if (!split.rest.isEmpty()) {
            builder.append("\n").append(split.rest);
        }

        return builder;
    }

    private void showStatus(int resId) {
        showStatus(getContext().getString(resId));
    }

    private void showStatus(CharSequence text) {
        mText.setText(text);
        mText.setTextColor(mStatusColor);
    }

    private static LayoutParams below(int gap) {
        LayoutParams params = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        params.topMargin = gap;

        return params;
    }

    private TextView text(Context context, int colorRes, int sizeRes) {
        TextView view = new TextView(context);
        view.setTextColor(getResources().getColor(colorRes));
        view.setTextSize(TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(sizeRes));

        return view;
    }
}
