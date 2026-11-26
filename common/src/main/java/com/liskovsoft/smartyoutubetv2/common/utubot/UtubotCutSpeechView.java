package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.misc.MotherActivity;

/**
 * "Describe by voice…" over the playing video: a mic the owner taps to record, the transcript the
 * backend returns in an editable box, and "Use this" to build the cut with it. The video is not
 * touched and keeps playing; Back takes the sheet away. The microphone results (permission and the
 * platform recogniser) are forwarded to {@link UtubotSpeechInput}.
 */
public final class UtubotCutSpeechView extends FrameLayout implements UtubotSpeechActivityHost, MotherActivity.OnResult {
    public interface OnDescriptionReady {
        void onDescription(String text);
    }

    private enum State {
        IDLE, RECORDING, TRANSCRIPT, ERROR
    }

    private static final int PULSE_HZ = 3;
    private static final int SCRIM = 0xD0000000;
    private static final int TEXT = 0xFFFFFFFF;
    private static final int MUTED = 0xB3FFFFFF;
    private static final int TITLE_SP = 20;
    private static final int BODY_SP = 16;
    private static final int PADDING = 48;

    private final UtubotSpeechInput mSpeech;
    private final OnDescriptionReady mOnReady;
    private final MotherActivity mActivity;
    private final LinearLayout mColumn;
    private final TextView mTitle;
    private final TextView mStatus;
    private final EditText mTranscript;
    private final Button mPrimary;
    private final Button mSecondary;

    private final String mLanguageHint;
    private final int mMaxSeconds;
    private final UtubotSpeechInput.Listener mDescribeListener;

    private State mState = State.IDLE;
    private boolean mActive = true;
    private final Runnable mPulse = new Runnable() {
        private boolean on = true;

        @Override
        public void run() {
            if (mState != State.RECORDING) {
                return;
            }
            mStatus.setTextColor(on ? Color.WHITE : 0x60FFFFFF);
            on = !on;
            postDelayed(this, 1000 / PULSE_HZ);
        }
    };

    private UtubotCutSpeechView(MotherActivity activity, UtubotClient client, OnDescriptionReady onReady,
                                @Nullable String languageHint, int maxSeconds) {
        super(activity);
        mActivity = activity;
        mOnReady = onReady;
        mLanguageHint = languageHint;
        mMaxSeconds = maxSeconds;
        setBackgroundColor(SCRIM);
        setClickable(true);
        setFocusable(true);
        setFocusableInTouchMode(true);
        setOnKeyListener((view, keyCode, event) -> {
            if (event.getAction() != KeyEvent.ACTION_DOWN) {
                return false;
            }

            switch (keyCode) {
                case KeyEvent.KEYCODE_VOLUME_UP:
                case KeyEvent.KEYCODE_VOLUME_DOWN:
                case KeyEvent.KEYCODE_VOLUME_MUTE:
                    return false; // the volume keys stay with the system
                case KeyEvent.KEYCODE_BACK:
                case KeyEvent.KEYCODE_ESCAPE:
                    close();
                    return true;
                default:
                    return false;
            }
        });

        mColumn = new LinearLayout(activity);
        mColumn.setOrientation(LinearLayout.VERTICAL);
        mColumn.setGravity(Gravity.CENTER_HORIZONTAL);
        mColumn.setPadding(PADDING, PADDING, PADDING, PADDING);
        addView(mColumn, new LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER));

        mTitle = new TextView(activity);
        mTitle.setTextColor(TEXT);
        mTitle.setTextSize(TITLE_SP);
        mTitle.setTypeface(Typeface.DEFAULT_BOLD);
        mTitle.setGravity(Gravity.CENTER);
        mColumn.addView(mTitle, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        mStatus = new TextView(activity);
        mStatus.setTextColor(MUTED);
        mStatus.setTextSize(BODY_SP);
        mStatus.setGravity(Gravity.CENTER);
        mColumn.addView(mStatus, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams statusParams = (LinearLayout.LayoutParams) mStatus.getLayoutParams();
        statusParams.topMargin = 12;

        mTranscript = new EditText(activity);
        mTranscript.setBackgroundColor(0x33FFFFFF);
        mTranscript.setTextColor(TEXT);
        mTranscript.setTypeface(Typeface.DEFAULT);
        mTranscript.setTextSize(BODY_SP);
        mTranscript.setHint(R.string.utubot_speech_edit);
        mTranscript.setMaxLines(6);
        mTranscript.setGravity(Gravity.TOP | Gravity.START);
        mTranscript.setPadding(16, 16, 16, 16);
        mTranscript.setVisibility(View.GONE);
        mColumn.addView(mTranscript, new LinearLayout.LayoutParams(
                Math.min(screenPx(activity) * 3 / 4, 900), LinearLayout.LayoutParams.WRAP_CONTENT));

        mPrimary = actionButton(R.string.utubot_speech_record, view -> onPrimary());
        mSecondary = actionButton(R.string.utubot_speech_record_again, view -> onSecondary());
        mSecondary.setVisibility(View.GONE);
        mColumn.addView(mPrimary, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        mColumn.addView(mSecondary, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        mDescribeListener = new UtubotSpeechInput.Listener() {
            @Override
            public void onProgress(String message) {
                post(() -> {
                    if (mState != State.RECORDING) {
                        mTranscript.setText("");
                        setState(State.RECORDING);
                    }
                });
            }

            @Override
            public void onText(String text) {
                post(() -> {
                    mTranscript.setText(text);
                    mTranscript.setSelection(text.length());
                    setState(State.TRANSCRIPT);
                });
            }

            @Override
            public void onError(String message) {
                post(() -> showError());
            }
        };

        mSpeech = new UtubotSpeechInput(activity, client);
        mSpeech.describe(languageHint, maxSeconds, mDescribeListener);

        mActivity.addOnResult(this);
        draw();
    }

    private Button actionButton(int labelRes, View.OnClickListener click) {
        Button button = new Button(mActivity);
        button.setTextColor(Color.BLACK);
        button.setBackgroundColor(0xFFC8F23A);
        button.setTextSize(BODY_SP);
        button.setOnClickListener(click);
        return button;
    }

    private static int screenPx(Context context) {
        DisplayMetrics metrics = context.getResources().getDisplayMetrics();
        return Math.min(metrics.widthPixels, metrics.heightPixels);
    }

    private void onPrimary() {
        if (mState == State.IDLE || mState == State.RECORDING) {
            setState(State.RECORDING);
        } else if (mState == State.TRANSCRIPT) {
            finish(mTranscript.getText().toString());
        }
    }

    private void onSecondary() {
        if (mState == State.TRANSCRIPT || mState == State.ERROR) {
            restart();
        }
    }

    private void restart() {
        mTranscript.setText("");
        mSpeech.describe(mLanguageHint, mMaxSeconds, mDescribeListener);
        post(() -> setState(State.RECORDING));
    }

    private void showError() {
        setState(State.ERROR);
    }

    private void finish(String text) {
        String description = text == null ? "" : text.trim();

        if (description.isEmpty()) {
            showError();
            return;
        }

        close();
        mOnReady.onDescription(description);
    }

    private void setState(State next) {
        mState = next;
        draw();
    }

    private void draw() {
        switch (mState) {
            case IDLE:
                mTitle.setText(R.string.utubot_cut_describe_by_voice);
                mStatus.setText(R.string.utubot_speech_record);
                mStatus.setVisibility(View.VISIBLE);
                mTranscript.setVisibility(View.GONE);
                mSecondary.setVisibility(View.GONE);
                mPrimary.setText(R.string.utubot_speech_record);
                mPrimary.setVisibility(View.VISIBLE);
                break;

            case RECORDING:
                mTitle.setText(R.string.utubot_cut_describe_by_voice);
                mStatus.setText(R.string.utubot_speech_recording);
                mStatus.setVisibility(View.VISIBLE);
                mTranscript.setVisibility(View.GONE);
                mSecondary.setVisibility(View.GONE);
                mPrimary.setText(R.string.utubot_speech_record);
                mPrimary.setVisibility(View.VISIBLE);
                post(mPulse);
                break;

            case TRANSCRIPT:
                mTitle.setText(R.string.utubot_speech_edit);
                mStatus.setText(R.string.utubot_speech_hint);
                mStatus.setVisibility(View.VISIBLE);
                mTranscript.setVisibility(View.VISIBLE);
                mSecondary.setVisibility(View.VISIBLE);
                mPrimary.setText(R.string.utubot_speech_use);
                mPrimary.setVisibility(View.VISIBLE);
                removeCallbacks(mPulse);
                break;

            case ERROR:
            default:
                mTitle.setText(R.string.utubot_cut_describe_by_voice);
                mStatus.setText(R.string.utubot_speech_no_mic);
                mStatus.setVisibility(View.VISIBLE);
                mTranscript.setVisibility(View.GONE);
                mSecondary.setVisibility(View.VISIBLE);
                mPrimary.setText(R.string.utubot_speech_record_again);
                mPrimary.setVisibility(View.VISIBLE);
                removeCallbacks(mPulse);
                break;
        }
    }

    @Override
    public void onUtubotSpeechActivityResult(int requestCode, int resultCode, Intent data) {
        mSpeech.onUtubotSpeechActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onResult(int requestCode, int resultCode, Intent data) {
        mSpeech.onUtubotSpeechActivityResult(requestCode, resultCode, data);
        if (mActive) {
            mActivity.addOnResult(this);
        }
    }

    /** Shows the sheet over the activity's content; the video is not touched. Back takes it away. */
    public static void show(Context context, UtubotClient client, OnDescriptionReady onReady, @Nullable String languageHint, int maxSeconds) {
        Activity activity = activityOf(context);

        if (!(activity instanceof MotherActivity)) {
            return;
        }

        ViewGroup content = activity.findViewById(android.R.id.content);
        close(content);
        content.addView(new UtubotCutSpeechView((MotherActivity) activity, client, onReady, languageHint, maxSeconds),
                new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private static void close(ViewGroup content) {
        for (int i = content.getChildCount() - 1; i >= 0; i--) {
            if (content.getChildAt(i) instanceof UtubotCutSpeechView) {
                content.removeViewAt(i);
            }
        }
    }

    private void close() {
        mActive = false;
        mSpeech.cancel();
        removeCallbacks(mPulse);

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
