package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;
import android.view.Gravity;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;
import com.liskovsoft.smartyoutubetv2.tv.R;

import java.util.ArrayList;
import java.util.List;

/**
 * The Summary panel: the title, the prompt select box, a status line and the scrollable summary. Drawn over the right side of
 * an activity, the content below stays usable.
 */
public class UtubotPanelView extends LinearLayout {
    public interface OnPromptPicked {
        void onPicked(String key);
    }

    private final TextView mTitle;
    private final Spinner mSpinner;
    private final TextView mStatus;
    private final ScrollView mScroll;
    private final TextView mText;
    private final List<String> mKeys = new ArrayList<>();
    private OnPromptPicked mOnPromptPicked;
    private boolean mIsBinding;
    private String mCurrentKey;

    public UtubotPanelView(Context context) {
        super(context);
        setOrientation(VERTICAL);
        setBackgroundColor(getResources().getColor(R.color.utubot_panel_background));
        int padding = getResources().getDimensionPixelSize(R.dimen.utubot_panel_padding);
        int gap = getResources().getDimensionPixelSize(R.dimen.utubot_panel_gap);
        setPadding(padding, padding, padding, padding);
        setVisibility(GONE);

        mTitle = new TextView(context);
        mTitle.setTextColor(getResources().getColor(R.color.utubot_panel_title));
        mTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.utubot_panel_title_size));
        mTitle.setMaxLines(getResources().getInteger(R.integer.utubot_panel_title_lines));
        mTitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
        addView(mTitle, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));

        mSpinner = new Spinner(context);
        mSpinner.setMinimumHeight(getResources().getDimensionPixelSize(R.dimen.utubot_panel_spinner_min_height));
        mSpinner.setFocusable(true);
        mSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (!mIsBinding && mOnPromptPicked != null && position < mKeys.size() && !mKeys.get(position).equals(mCurrentKey)) {
                    mCurrentKey = mKeys.get(position);
                    mOnPromptPicked.onPicked(mCurrentKey);
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        LayoutParams spinnerParams = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        spinnerParams.topMargin = gap;
        addView(mSpinner, spinnerParams);

        mStatus = new TextView(context);
        mStatus.setTextColor(getResources().getColor(R.color.utubot_panel_status));
        mStatus.setTextSize(android.util.TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.utubot_panel_status_size));
        LayoutParams statusParams = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        statusParams.topMargin = gap;
        addView(mStatus, statusParams);

        mText = new TextView(context);
        mText.setTextColor(getResources().getColor(R.color.utubot_panel_text));
        mText.setTextSize(android.util.TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.utubot_panel_text_size));
        mScroll = new ScrollView(context);
        mScroll.setFocusable(true);
        mScroll.setFocusableInTouchMode(false);
        mScroll.addView(mText);
        LayoutParams scrollParams = new LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f);
        scrollParams.topMargin = gap;
        addView(mScroll, scrollParams);
    }

    /**
     * The layout params of the panel inside an activity's content: the right side, the configured share of the width
     */
    public static FrameLayout.LayoutParams layoutParams(Context context, int parentWidthPx) {
        int percent = context.getResources().getInteger(R.integer.utubot_panel_width_percent);
        return new FrameLayout.LayoutParams(parentWidthPx * percent / PERCENT, FrameLayout.LayoutParams.MATCH_PARENT, Gravity.END);
    }

    private static final int PERCENT = 100;

    public void setOnPromptPicked(OnPromptPicked listener) {
        mOnPromptPicked = listener;
    }

    public void bind(State state) {
        mTitle.setText(state.video != null ? state.video.getTitle() : "");
        mCurrentKey = state.selectedKey;
        bindPrompts(state);
        mScroll.scrollTo(0, 0);

        switch (state.phase) {
            case LOADING:
                mStatus.setText(R.string.utubot_panel_loading);
                mText.setText("");
                break;
            case READY:
                mStatus.setText(getContext().getString(R.string.utubot_panel_ready, state.source != null ? state.source : "-"));
                mText.setText(state.text != null && !state.text.isEmpty() ? state.text : getContext().getString(R.string.utubot_panel_empty));
                break;
            case FAILED:
                mStatus.setText(getContext().getString(R.string.utubot_panel_failed, state.error != null ? state.error : "-"));
                mText.setText("");
                break;
            default:
                mStatus.setText("");
                mText.setText("");
        }
    }

    private void bindPrompts(State state) {
        List<String> keys = new ArrayList<>();
        List<String> labels = new ArrayList<>();

        for (Prompt prompt : state.prompts) {
            keys.add(prompt.key);
            labels.add(prompt.label);
        }

        if (keys.equals(mKeys) && state.phase != Phase.IDLE) {
            selectKey(state.selectedKey);
            return;
        }

        mIsBinding = true;
        mKeys.clear();
        mKeys.addAll(keys);
        mSpinner.setAdapter(new ArrayAdapter<>(getContext(), android.R.layout.simple_spinner_dropdown_item, labels));
        selectKey(state.selectedKey);
        mSpinner.post(() -> mIsBinding = false);
    }

    private void selectKey(String key) {
        int index = key != null ? mKeys.indexOf(key) : -1;

        if (index >= 0 && mSpinner.getSelectedItemPosition() != index) {
            mIsBinding = true;
            mSpinner.setSelection(index);
            mSpinner.post(() -> mIsBinding = false);
        }
    }

    /**
     * The select box takes the focus
     */
    public boolean focusPrompt() {
        return getVisibility() == VISIBLE && mSpinner.requestFocus();
    }

    public boolean hasPanelFocus() {
        return getVisibility() == VISIBLE && findFocus() != null;
    }
}
