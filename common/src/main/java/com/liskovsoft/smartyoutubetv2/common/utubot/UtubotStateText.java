package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

/**
 * The words of the transcript states, shared by the passive panel, the Summary view and the answer: what the backend said wins over
 * the app's own words, which are the fallback for a backend that sent none.
 */
public final class UtubotStateText {
    private UtubotStateText() {
    }

    private static final int SECONDS_PER_MINUTE = 60;

    /**
     * The panel's text for a video without captions: what the backend says (it knows whether captions are missing or only limited, and
     * how long a transcription takes), else the way to the transcription or why there is none
     */
    public static String noCaptionsShort(Context context, State state) {
        if (hasText(state.message)) {
            return state.message;
        }

        return context.getString(state.canTranscribe ? R.string.utubot_panel_no_captions : R.string.utubot_panel_no_transcript);
    }

    /**
     * The Summary view's text for a video without captions
     */
    public static String noCaptionsLong(Context context, State state) {
        if (hasText(state.message)) {
            return state.message;
        }

        return context.getString(state.canTranscribe ? R.string.utubot_view_no_captions : R.string.utubot_panel_no_transcript);
    }

    /**
     * Why the backend is waiting: what it said (its error), else the app's own words
     */
    public static String delayed(Context context, State state) {
        return hasText(state.message) ? state.message : context.getString(R.string.utubot_panel_delayed);
    }

    /**
     * The time left before the delayed request is asked again: "Retrying in 42 s", "Retrying in 2:05", empty when not counting
     */
    public static String retryIn(Context context, State state) {
        if (state.retryInSec <= 0) {
            return "";
        }

        if (state.retryInSec < SECONDS_PER_MINUTE) {
            return context.getString(R.string.utubot_panel_retry_in_seconds, state.retryInSec);
        }

        return context.getString(R.string.utubot_panel_retry_in_minutes, state.retryInSec / SECONDS_PER_MINUTE, state.retryInSec % SECONDS_PER_MINUTE);
    }

    /**
     * The panel's text for a delayed request: the backend's words, then the countdown
     */
    public static String delayedWithCountdown(Context context, State state) {
        String countdown = retryIn(context, state);
        String reason = delayed(context, state);

        return countdown.isEmpty() ? reason : reason + "\n" + countdown;
    }

    /**
     * "Transcribing… 40% (~4 min)": the progress when it is known, the backend's estimate when it gave one
     */
    public static String transcribing(Context context, State state) {
        boolean hasProgress = state.progressPercent >= 0;
        boolean hasEstimate = state.estimateMinutes > 0;

        if (hasProgress && hasEstimate) {
            return context.getString(R.string.utubot_panel_transcribing_percent_estimate, state.progressPercent, state.estimateMinutes);
        }

        if (hasProgress) {
            return context.getString(R.string.utubot_panel_transcribing_percent, state.progressPercent);
        }

        if (hasEstimate) {
            return context.getString(R.string.utubot_panel_transcribing_estimate, state.estimateMinutes);
        }

        return context.getString(R.string.utubot_panel_transcribing);
    }

    /**
     * The label of the button that starts the transcription: "Transcribe in background (~4 min)"
     */
    public static String transcribeAction(Context context, State state) {
        if (state.estimateMinutes <= 0) {
            return context.getString(R.string.utubot_view_transcribe);
        }

        return context.getString(R.string.utubot_view_transcribe_minutes, state.estimateMinutes);
    }

    private static boolean hasText(@Nullable String text) {
        return text != null && !text.trim().isEmpty();
    }
}
