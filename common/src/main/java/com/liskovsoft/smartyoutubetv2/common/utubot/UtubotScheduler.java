package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.os.Handler;
import android.os.Looper;

/**
 * Delayed tasks, injected into the u-tubot timing logic so tests can drive the clock
 */
public interface UtubotScheduler {
    void postDelayed(Runnable task, long delayMs);

    void remove(Runnable task);

    /**
     * Runs the tasks on the main thread
     */
    static UtubotScheduler mainThread() {
        Handler handler = new Handler(Looper.getMainLooper());

        return new UtubotScheduler() {
            @Override
            public void postDelayed(Runnable task, long delayMs) {
                handler.postDelayed(task, delayMs);
            }

            @Override
            public void remove(Runnable task) {
                handler.removeCallbacks(task);
            }
        };
    }
}
