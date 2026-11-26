package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.util.HashMap;
import java.util.Map;

/**
 * Decides which of the app's own failures are worth reporting to the backend's error ledger: one report per
 * distinct operation and message per window, and no more than a fixed number per window overall, so a dead
 * backend or a retry loop never floods the ledger.
 */
final class UtubotFailureThrottle {
    static final long WINDOW_MS = 60_000;
    static final int MAX_PER_WINDOW = 10;

    private final Map<String, Long> mLastSent = new HashMap<>();
    private long mWindowStartMs;
    private int mSentInWindow;

    synchronized boolean shouldReport(String operation, String message, long nowMs) {
        if (nowMs - mWindowStartMs >= WINDOW_MS) {
            mWindowStartMs = nowMs;
            mSentInWindow = 0;
            mLastSent.clear();
        }

        String key = operation + "|" + message;

        if (mLastSent.containsKey(key) || mSentInWindow >= MAX_PER_WINDOW) {
            return false;
        }

        mLastSent.put(key, nowMs);
        mSentInWindow++;
        return true;
    }
}
