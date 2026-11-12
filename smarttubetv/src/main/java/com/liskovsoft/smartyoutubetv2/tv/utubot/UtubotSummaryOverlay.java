package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;
import android.graphics.Typeface;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.FocusFinder;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Action;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotStateText;
import com.liskovsoft.smartyoutubetv2.tv.R;

import java.util.ArrayList;
import java.util.List;

/**
 * The focused Summary view, a full-height card over the browse screen: the prompts of the backend on the left, the summary text on the
 * right, the title, the source, the working indicator and Retry on top. Also the AI answer (no prompt list). The focus stays inside
 * it: Up and Down move through the prompts (the summary follows after a short rest) or scroll the text, Right goes to the text, Left
 * back to the prompts. Back is handled by the controller.
 */
public class UtubotSummaryOverlay extends FrameLayout {
    interface Listener {
        void onRetry();

        /** The button of a video without captions: have the audio transcribed in the background */
        void onTranscribe();

        /** The prompt highlight rests on a key (the summary of it loads) */
        void onHighlight(String key);

        /** OK on a prompt: kept for the session */
        void onPick(String key);
    }

    private final TextView mTitle;
    private final UtubotWorkingIndicator mIndicator;
    private final TextView mRetry;
    private final TextView mStatus;
    private final LinearLayout mListColumn;
    private final ListView mList;
    private final PromptAdapter mAdapter;
    private final UtubotPageScrollView mScroll;
    private final TextView mText;
    private final TextView mHint;
    private final List<String> mKeys = new ArrayList<>();
    private Listener mListener;
    private boolean mIsAnswer;
    private Action mAction = Action.NONE;
    /** The view was just opened and its first answer hasn't come yet */
    private boolean mIsFirstAnswerPending;
    /** The phase of the last state shown: a countdown re-binds the same phase every second and must not move the focus */
    @Nullable private Phase mBoundPhase;

    public UtubotSummaryOverlay(Context context) {
        super(context);
        setBackgroundColor(getResources().getColor(R.color.utubot_overlay_scrim));
        setVisibility(GONE);
        setClickable(true);
        int padding = getResources().getDimensionPixelSize(R.dimen.utubot_overlay_padding);
        int gap = getResources().getDimensionPixelSize(R.dimen.utubot_overlay_gap);

        LinearLayout card = new LinearLayout(context);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackgroundResource(R.drawable.utubot_overlay_card);
        card.setPadding(padding, padding, padding, padding);
        LayoutParams cardParams = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT);
        cardParams.setMargins(getResources().getDimensionPixelSize(R.dimen.utubot_overlay_margin_horizontal),
                getResources().getDimensionPixelSize(R.dimen.utubot_overlay_margin_vertical),
                getResources().getDimensionPixelSize(R.dimen.utubot_overlay_margin_horizontal),
                getResources().getDimensionPixelSize(R.dimen.utubot_overlay_margin_vertical));
        addView(card, cardParams);

        LinearLayout header = new LinearLayout(context);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        mTitle = text(R.color.utubot_panel_title, R.dimen.utubot_overlay_title_size);
        mTitle.setMaxLines(2);
        mTitle.setEllipsize(TextUtils.TruncateAt.END);
        header.addView(mTitle, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f));
        mIndicator = new UtubotWorkingIndicator(context);
        LinearLayout.LayoutParams indicatorParams = new LinearLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        indicatorParams.leftMargin = gap;
        indicatorParams.rightMargin = gap;
        header.addView(mIndicator, indicatorParams);
        mRetry = text(R.color.utubot_panel_title, R.dimen.utubot_overlay_status_size);
        mRetry.setId(R.id.utubot_overlay_retry);
        mRetry.setText(R.string.utubot_view_retry);
        mRetry.setFocusable(true);
        mRetry.setClickable(true);
        mRetry.setBackgroundResource(R.drawable.utubot_button_background);
        mRetry.setPadding(padding, gap, padding, gap);
        mRetry.setVisibility(GONE);
        mRetry.setOnClickListener(view -> {
            if (mListener == null) {
                return;
            }

            if (mAction == Action.TRANSCRIBE) {
                mListener.onTranscribe();
            } else {
                mListener.onRetry();
            }
        });
        header.addView(mRetry, new LinearLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT));
        card.addView(header, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));

        mStatus = text(R.color.utubot_panel_status, R.dimen.utubot_overlay_status_size);
        mStatus.setSingleLine(true);
        mStatus.setEllipsize(TextUtils.TruncateAt.END);
        card.addView(mStatus, below(gap));

        LinearLayout body = new LinearLayout(context);
        body.setOrientation(LinearLayout.HORIZONTAL);

        mListColumn = new LinearLayout(context);
        mListColumn.setOrientation(LinearLayout.VERTICAL);
        TextView listTitle = text(R.color.utubot_panel_label, R.dimen.utubot_overlay_status_size);
        listTitle.setText(R.string.utubot_view_prompts);
        mListColumn.addView(listTitle, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        mList = new ListView(context);
        mList.setId(R.id.utubot_overlay_list);
        mList.setDivider(null);
        mList.setSelector(R.drawable.utubot_focus_background);
        mList.setItemsCanFocus(false);
        mAdapter = new PromptAdapter(context);
        mList.setAdapter(mAdapter);
        mList.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (mListener != null && position >= 0 && position < mKeys.size()) {
                    mListener.onHighlight(mKeys.get(position));
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        mList.setOnItemClickListener((parent, view, position, id) -> {
            if (mListener != null && position < mKeys.size()) {
                mListener.onPick(mKeys.get(position));
            }
        });
        LinearLayout.LayoutParams listParams = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f);
        listParams.topMargin = gap;
        mListColumn.addView(mList, listParams);
        LinearLayout.LayoutParams columnParams = new LinearLayout.LayoutParams(0, LayoutParams.MATCH_PARENT,
                getResources().getInteger(R.integer.utubot_overlay_list_weight));
        columnParams.rightMargin = padding;
        body.addView(mListColumn, columnParams);

        mScroll = new UtubotPageScrollView(context);
        mScroll.setId(R.id.utubot_overlay_text);
        mText = text(R.color.utubot_panel_text, R.dimen.utubot_overlay_text_size);
        mText.setLineSpacing(0f, 1.15f);
        mText.setPadding(padding, gap, padding, gap);
        mScroll.addView(mText, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        body.addView(mScroll, new LinearLayout.LayoutParams(0, LayoutParams.MATCH_PARENT, getResources().getInteger(R.integer.utubot_overlay_text_weight)));

        mList.setNextFocusRightId(R.id.utubot_overlay_text);
        LinearLayout.LayoutParams bodyParams = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f);
        bodyParams.topMargin = gap;
        card.addView(body, bodyParams);

        mHint = text(R.color.utubot_panel_hint, R.dimen.utubot_overlay_hint_size);
        mHint.setSingleLine(true);
        mHint.setEllipsize(TextUtils.TruncateAt.END);
        card.addView(mHint, below(gap));
    }

    void setListener(Listener listener) {
        mListener = listener;
    }

    /**
     * Shows the view with nothing in it yet. The focus goes to the prompt list, or to the text for an answer.
     *
     * @param isAnswer the AI answer: no prompt list
     */
    void open(boolean isAnswer) {
        mIsAnswer = isAnswer;
        mKeys.clear();
        mAdapter.setItems(new ArrayList<>(), null);
        mListColumn.setVisibility(isAnswer ? GONE : VISIBLE);
        mScroll.setNextFocusLeftId(isAnswer ? NO_ID : R.id.utubot_overlay_list);
        mHint.setText(isAnswer ? R.string.utubot_view_answer_hint : R.string.utubot_view_hint);
        mText.setText("");
        mScroll.scrollTo(0, 0);
        mRetry.setVisibility(GONE);
        mAction = Action.NONE;
        mIsFirstAnswerPending = true;
        mBoundPhase = null;
        mIndicator.setActive(false);
        setVisibility(VISIBLE);
        restoreFocus();
    }

    void close() {
        setVisibility(GONE);
        mIndicator.setActive(false);
        mText.setText("");
    }

    boolean isOpen() {
        return getVisibility() == VISIBLE;
    }

    boolean isAnswer() {
        return mIsAnswer;
    }

    void bind(State state) {
        mTitle.setText(state.video != null ? state.video.getTitle() : "");
        mIndicator.setActive(state.isWorking());
        bindAction(state);
        bindPrompts(state);

        switch (state.phase) {
            case LOADING:
                mStatus.setText(mIsAnswer ? R.string.utubot_answer_loading : R.string.utubot_panel_loading);
                mText.setText("");
                break;
            case PENDING:
                mStatus.setText(R.string.utubot_panel_pending);
                mText.setText("");
                break;
            case NEEDS_TRANSCRIPT:
                mStatus.setText(state.promptLabel != null ? state.promptLabel : "");
                mText.setText(UtubotStateText.noCaptionsLong(getContext(), state));
                break;
            case DELAYED:
                mStatus.setText(UtubotStateText.retryIn(getContext(), state));
                mText.setText(UtubotStateText.delayed(getContext(), state));
                break;
            case TRANSCRIBING:
                mStatus.setText(UtubotStateText.transcribing(getContext(), state));
                mText.setText(R.string.utubot_view_transcribing_hint);
                break;
            case READY:
                mStatus.setText(sourceLine(state));
                mText.setText(state.text != null && !state.text.isEmpty() ? state.text : getContext().getString(R.string.utubot_panel_empty));
                mScroll.scrollTo(0, 0);
                break;
            case FAILED:
                mStatus.setText(getContext().getString(R.string.utubot_panel_failed, state.error != null ? state.error : "-"));
                mText.setText("");
                break;
            default:
                mStatus.setText("");
                mText.setText("");
        }

        // Nothing to read: the only thing to do is the button (ask again, or transcribe). On the first answer of a view that asks for a
        // transcription it takes the focus from the list, which the user hasn't used yet.
        boolean isFirstOffer = mIsFirstAnswerPending && mAction == Action.TRANSCRIBE;

        boolean isNewPhase = state.phase != mBoundPhase;
        mBoundPhase = state.phase;

        if (mAction != Action.NONE && ((mScroll.hasFocus() && isNewPhase) || isFirstOffer)) {
            mRetry.requestFocus();
        }

        if (state.phase != Phase.LOADING && state.phase != Phase.WAITING) {
            mIsFirstAnswerPending = false;
        }
    }

    /**
     * The header's button: Retry, or the transcription of a video without captions. It goes when there is nothing to do; the focus
     * it had goes back to the text.
     */
    private void bindAction(State state) {
        mAction = state.action();

        if (mAction == Action.NONE) {
            boolean hadFocus = mRetry.hasFocus();
            mRetry.setVisibility(GONE);

            if (hadFocus) {
                restoreFocus();
            }

            return;
        }

        mRetry.setText(mAction == Action.TRANSCRIBE ? UtubotStateText.transcribeAction(getContext(), state) : getContext().getString(R.string.utubot_view_retry));
        mRetry.setVisibility(VISIBLE);
    }

    private String sourceLine(State state) {
        String source = state.source != null ? state.source : "-";

        if (state.promptLabel == null) {
            return getContext().getString(R.string.utubot_panel_ready, source);
        }

        return getContext().getString(R.string.utubot_view_source_line, state.promptLabel, source);
    }

    /**
     * The list follows the state only when the prompts change: the highlight is the user's, and a late state must not pull it back
     */
    private void bindPrompts(State state) {
        List<String> keys = new ArrayList<>();
        List<String> labels = new ArrayList<>();

        for (Prompt prompt : state.prompts) {
            keys.add(prompt.key);
            labels.add(prompt.label);
        }

        if (!keys.equals(mKeys)) {
            boolean isFirstList = mKeys.isEmpty() && !keys.isEmpty();
            mKeys.clear();
            mKeys.addAll(keys);
            mAdapter.setItems(labels, state.selectedKey != null ? state.selectedKey : null);
            int index = state.selectedKey != null ? mKeys.indexOf(state.selectedKey) : -1;

            if (index >= 0) {
                mList.setSelection(index);
            }

            // The list couldn't take the focus while it was empty: the view's focus waited on the text
            if (isFirstList && !mIsAnswer && !mList.hasFocus() && !mRetry.hasFocus()) {
                mList.requestFocus();
            }
        } else {
            mAdapter.setCurrent(state.selectedKey);
        }
    }

    /**
     * Keeps the focus inside the view: nothing of the screen below can take it
     */
    @Override
    public View focusSearch(View focused, int direction) {
        return FocusFinder.getInstance().findNextFocus(this, focused, direction);
    }

    /**
     * Gives the focus back to the list (the text for an answer, or while there is no list yet: an empty list can't take the focus),
     * when the screen below took it
     */
    void restoreFocus() {
        (mIsAnswer || mKeys.isEmpty() ? mScroll : mList).requestFocus();
    }

    private static LinearLayout.LayoutParams below(int gap) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        params.topMargin = gap;

        return params;
    }

    private TextView text(int colorRes, int sizeRes) {
        TextView view = new TextView(getContext());
        view.setTextColor(getResources().getColor(colorRes));
        view.setTextSize(TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(sizeRes));

        return view;
    }

    /**
     * The prompt labels: the one whose summary is shown is brighter and bold
     */
    private final class PromptAdapter extends ArrayAdapter<String> {
        private final List<String> mLabels = new ArrayList<>();
        private String mCurrentKey;

        PromptAdapter(Context context) {
            super(context, 0);
        }

        void setItems(List<String> labels, @Nullable String currentKey) {
            mLabels.clear();
            mLabels.addAll(labels);
            mCurrentKey = currentKey;
            notifyDataSetChanged();
        }

        void setCurrent(@Nullable String key) {
            if (key != null && !key.equals(mCurrentKey) || key == null && mCurrentKey != null) {
                mCurrentKey = key;
                notifyDataSetChanged();
            }
        }

        @Override
        public int getCount() {
            return mLabels.size();
        }

        @Nullable
        @Override
        public String getItem(int position) {
            return mLabels.get(position);
        }

        @Override
        public View getView(int position, @Nullable View convertView, ViewGroup parent) {
            TextView view = convertView instanceof TextView ? (TextView) convertView : text(R.color.utubot_panel_text, R.dimen.utubot_overlay_item_size);
            int pad = getResources().getDimensionPixelSize(R.dimen.utubot_overlay_item_padding);
            view.setPadding(pad, pad, pad, pad);
            view.setText(mLabels.get(position));
            boolean isCurrent = position < mKeys.size() && mKeys.get(position).equals(mCurrentKey);
            view.setTextColor(getResources().getColor(isCurrent ? R.color.utubot_overlay_current : R.color.utubot_panel_text));
            view.setTypeface(null, isCurrent ? Typeface.BOLD : Typeface.NORMAL);

            return view;
        }
    }
}
