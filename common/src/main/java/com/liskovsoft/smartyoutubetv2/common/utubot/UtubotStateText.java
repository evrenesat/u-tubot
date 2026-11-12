package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

/**
 * The words of the transcript states, shared by the passive panel, the Summary view and the answer: what the backend said wins over
 * the app's own words, which are the fallback for a backend that sent none.
 */
public final class UtubotStateText {
    private UtubotStateText() {
    }

    /**
     * The panel's one short line for a video without captions: the way to the transcription, or why there is none
     */
    public static String noCaptionsShort(Context context, State state) {
        if (state.canTranscribe) {
            return context.getString(R.string.utubot_panel_no_captions);
        }

        return state.message != null ? state.message : context.getString(R.string.utubot_panel_no_transcript);
    }

    /**
     * The Summary view's text for a video without captions
     */
    public static String noCaptionsLong(Context context, State state) {
        if (state.message != null) {
            return state.message;
        }

        return context.getString(state.canTranscribe ? R.string.utubot_view_no_captions : R.string.utubot_panel_no_transcript);
    }

    public static String delayed(Context context, State state) {
        return state.message != null ? state.message : context.getString(R.string.utubot_panel_delayed);
    }

    /**
     * "Transcribing… 40%", or without the number while the progress isn't known
     */
    public static String transcribing(Context context, State state) {
        if (state.progressPercent < 0) {
            return context.getString(R.string.utubot_panel_transcribing);
        }

        return context.getString(R.string.utubot_panel_transcribing_percent, state.progressPercent);
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
}
