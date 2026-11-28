package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Finds a frozen main thread without a busy loop: a daemon thread posts a flag to the main thread every {@link #CHECK_MS} and sleeps.
 * When the flag is not set a whole period later, the main thread's stack is recorded once as an "anr" failure (see AppExits). It does
 * nothing while the app is in the background, where the system may legitimately hold the main thread.
 */
public final class AnrWatchdog implements Runnable {
    public static final long CHECK_MS = 5_000;
    private static final int MAX_FRAMES = 40;
    private static final AtomicBoolean sStarted = new AtomicBoolean();
    private final Context mContext;
    private final Handler mMain = new Handler(Looper.getMainLooper());
    private final AtomicBoolean mAcked = new AtomicBoolean(true);
    private final Runnable mAck = () -> mAcked.set(true);

    private AnrWatchdog(Context context) {
        mContext = context.getApplicationContext();
    }

    public static void start(Context context) {
        if (!sStarted.compareAndSet(false, true)) {
            return;
        }

        Thread thread = new Thread(new AnrWatchdog(context), "utubot-anr-watchdog");
        thread.setDaemon(true);
        thread.setPriority(Thread.MIN_PRIORITY);
        thread.start();
    }

    @Override
    public void run() {
        boolean reported = false;

        while (!Thread.currentThread().isInterrupted()) {
            if (mAcked.get()) {
                reported = false;
                mAcked.set(false);
                mMain.post(mAck);
            } else if (!reported && Helpers.isAppInForeground()) {
                reported = true;
                record();
            }

            try {
                Thread.sleep(CHECK_MS);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    private void record() {
        try {
            String stack = stackOf(Looper.getMainLooper().getThread().getStackTrace());
            UtubotPlayerLog.event("anr", "main thread blocked for " + CHECK_MS + " ms or more");
            PlayerFailure.create(mContext, AppExits.KIND_ANR).detail("stack", stack).recordNow();
            UtubotPlayerLog.flushNow();
        } catch (RuntimeException e) {
            // Nothing is to come out of the watchdog itself
        }
    }

    static String stackOf(StackTraceElement[] frames) {
        StringBuilder text = new StringBuilder();

        for (int i = 0; i < Math.min(MAX_FRAMES, frames.length); i++) {
            text.append(frames[i]).append('\n');
        }

        return text.toString();
    }
}
