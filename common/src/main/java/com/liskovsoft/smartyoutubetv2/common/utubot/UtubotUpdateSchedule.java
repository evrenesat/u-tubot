package com.liskovsoft.smartyoutubetv2.common.utubot;

/**
 * When the app checks for updates by itself: once shortly after the app starts, then every {@link #INTERVAL_MS} while it runs.
 * A check that can't happen now (the player is open, the app is in the background, a dialog is up) is tried again after
 * {@link #RETRY_MS}. So is a check that found an update it could not show (the player opened or the app went to the background
 * while the update was being fetched): sooner, {@link #SETTLE_MS} after the next screen comes up (the player closed).
 */
public final class UtubotUpdateSchedule {
    public static final long START_DELAY_MS = 20_000;
    public static final long INTERVAL_MS = 6L * 60 * 60 * 1000;
    public static final long RETRY_MS = 5L * 60 * 1000;
    /** How long a screen that came back (the player closed) rests before an update that waits for it is offered */
    public static final long SETTLE_MS = 5_000;

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
    private boolean mIsDeferred;

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
        mIsDeferred = false;
        mScheduler.remove(mRun);
    }

    /**
     * A check found an update and could not show it now (the player is open, the app is in the background): the next check is
     * {@link #RETRY_MS} away instead of {@link #INTERVAL_MS}, and {@link #onScreenAvailable()} brings it closer.
     */
    public void onUpdateDeferred() {
        if (!mIsStarted) {
            return;
        }

        mIsDeferred = true;
        mScheduler.remove(mRun);
        mScheduler.postDelayed(mRun, RETRY_MS);
    }

    /**
     * A screen that can show the update dialog came up (the player closed, the app came back): an update that waits for one is
     * offered after {@link #SETTLE_MS}. Nothing when none waits.
     */
    public void onScreenAvailable() {
        if (!mIsStarted || !mIsDeferred) {
            return;
        }

        mScheduler.remove(mRun);
        mScheduler.postDelayed(mRun, SETTLE_MS);
    }

    private void run() {
        boolean isChecked;
        mIsDeferred = false;

        try {
            isChecked = mCheck.run();
        } catch (RuntimeException e) {
            isChecked = false;
        }

        // Once only: a deferral during the check has already queued the retry
        mScheduler.remove(mRun);
        mScheduler.postDelayed(mRun, isChecked && !mIsDeferred ? INTERVAL_MS : RETRY_MS);
    }
}
