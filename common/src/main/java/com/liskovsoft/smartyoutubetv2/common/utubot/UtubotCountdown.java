package com.liskovsoft.smartyoutubetv2.common.utubot;

/**
 * Counts whole seconds down on the scheduler: the owner hears every second that is left and the moment it runs out. Used for the
 * wait before a delayed request is asked again ("Retrying in 42 s").
 */
final class UtubotCountdown {
    private static final long TICK_MS = 1_000;

    interface Listener {
        /** @param remainingSec the seconds still to wait, at least 1 */
        void onTick(int remainingSec);

        void onDone();
    }

    private final UtubotScheduler mTimer;
    private final Listener mListener;
    private final Runnable mTickTask = this::tick;
    private int mRemainingSec;

    UtubotCountdown(UtubotScheduler timer, Listener listener) {
        mTimer = timer;
        mListener = listener;
    }

    /**
     * Starts counting from the given seconds, a countdown that is running is dropped
     */
    void start(int seconds) {
        cancel();
        mRemainingSec = seconds;
        mTimer.postDelayed(mTickTask, TICK_MS);
    }

    void cancel() {
        mTimer.remove(mTickTask);
    }

    private void tick() {
        mRemainingSec--;

        if (mRemainingSec <= 0) {
            mListener.onDone();
            return;
        }

        mListener.onTick(mRemainingSec);
        mTimer.postDelayed(mTickTask, TICK_MS);
    }
}
