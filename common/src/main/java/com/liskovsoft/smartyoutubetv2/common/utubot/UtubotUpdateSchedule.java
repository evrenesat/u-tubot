package com.liskovsoft.smartyoutubetv2.common.utubot;

/**
 * When the app checks for updates by itself: once shortly after the app starts, then every {@link #INTERVAL_MS} while it runs.
 * A check that can't happen now (the player is open, the app is in the background, a dialog is up) is tried again after
 * {@link #RETRY_MS}.
 */
public final class UtubotUpdateSchedule {
    public static final long START_DELAY_MS = 20_000;
    public static final long INTERVAL_MS = 6L * 60 * 60 * 1000;
    public static final long RETRY_MS = 5L * 60 * 1000;

    public interface Check {
        /**
         * @return true when a check was made, false when it wasn't possible now
         */
        boolean run();
    }

    private final UtubotScheduler mScheduler;
    private final Check mCheck;
    private final Runnable mRun = this::run;
    private boolean mIsStarted;

    public UtubotUpdateSchedule(UtubotScheduler scheduler, Check check) {
        mScheduler = scheduler;
        mCheck = check;
    }

    /**
     * Starts the schedule, once: later calls (each start of the app's screens) change nothing
     */
    public void start() {
        if (mIsStarted) {
            return;
        }

        mIsStarted = true;
        mScheduler.postDelayed(mRun, START_DELAY_MS);
    }

    public void stop() {
        mIsStarted = false;
        mScheduler.remove(mRun);
    }

    private void run() {
        boolean isChecked;

        try {
            isChecked = mCheck.run();
        } catch (RuntimeException e) {
            isChecked = false;
        }

        mScheduler.postDelayed(mRun, isChecked ? INTERVAL_MS : RETRY_MS);
    }
}
