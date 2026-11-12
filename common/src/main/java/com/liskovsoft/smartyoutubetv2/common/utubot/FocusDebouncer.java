package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import java.util.function.LongSupplier;

/**
 * Settles on a key once it has kept the focus for a whole pause. Every focus change, and every {@link #touch()} while a key is
 * pending (a held D-pad key), starts the pause again, so nothing settles while the user keeps moving. The clock is the injected
 * scheduler, which keeps the logic testable without Android.
 */
public final class FocusDebouncer {
    public interface Listener {
        /**
         * A key took the focus and waits for its pause. Whatever was loading for the previous key is to be dropped.
         */
        void onPending(String key);

        /**
         * The key kept the focus for the whole pause
         */
        void onSettled(String key);
    }

    private final UtubotScheduler mScheduler;
    private final LongSupplier mDelayMs;
    private final Listener mListener;
    private final Runnable mSettle = this::settle;
    private String mPending;
    private String mSettled;

    /**
     * @param delayMs read at every start of the pause, so a changed setting applies at once
     */
    public FocusDebouncer(UtubotScheduler scheduler, LongSupplier delayMs, Listener listener) {
        mScheduler = scheduler;
        mDelayMs = delayMs;
        mListener = listener;
    }

    /**
     * @param key null: nothing is focused any more
     */
    public void focus(@Nullable String key) {
        if (key == null) {
            cancel();
            return;
        }

        if (key.equals(mPending)) {
            arm();
            return;
        }

        if (key.equals(mSettled)) {
            return;
        }

        mSettled = null;
        mPending = key;
        arm();
        mListener.onPending(key);
    }

    /**
     * The user is still moving (a key press or repeat): the pause of the pending key starts again
     */
    public void touch() {
        if (mPending != null) {
            arm();
        }
    }

    /**
     * Forgets the pending and the settled key
     */
    public void cancel() {
        mScheduler.remove(mSettle);
        mPending = null;
        mSettled = null;
    }

    public boolean isPending() {
        return mPending != null;
    }

    @Nullable
    public String getSettledKey() {
        return mSettled;
    }

    private void arm() {
        mScheduler.remove(mSettle);
        mScheduler.postDelayed(mSettle, mDelayMs.getAsLong());
    }

    private void settle() {
        String key = mPending;

        if (key == null) {
            return;
        }

        mPending = null;
        mSettled = key;
        mListener.onSettled(key);
    }
}
