package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.ErrorFragmentData;

/**
 * The empty or failed state of a u-tubot section of the sidebar (see the Processed section). It explains the state in the
 * section's own words, with no sign-in or close action: the backend is where the content comes from, not YouTube.
 */
public class UtubotSectionError implements ErrorFragmentData {
    private final String mMessage;

    private UtubotSectionError(String message) {
        mMessage = message;
    }

    /**
     * The backend answered with no video: a normal state, not a failure
     */
    public static UtubotSectionError empty(Context context) {
        return new UtubotSectionError(context.getString(R.string.utubot_processed_empty));
    }

    /**
     * The backend could not be reached or answered with an error
     */
    public static UtubotSectionError failed(Context context, @Nullable Throwable error) {
        String reason = error != null && error.getMessage() != null
                ? error.getMessage()
                : context.getString(R.string.utubot_error_connect);

        return new UtubotSectionError(context.getString(R.string.utubot_processed_failed, reason));
    }

    @Override
    public void onAction() {
    }

    @Override
    public String getMessage() {
        return mMessage;
    }

    @Override
    public String getActionText() {
        return null;
    }
}
