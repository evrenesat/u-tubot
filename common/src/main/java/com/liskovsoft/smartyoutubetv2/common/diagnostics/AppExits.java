package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import android.app.ActivityManager;
import android.app.ActivityManager.RunningAppProcessInfo;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build.VERSION;

import androidx.annotation.Nullable;
import androidx.annotation.RequiresApi;

import com.liskovsoft.smartyoutubetv2.common.prefs.DebuggingData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * The app dying, to the player failure log: a crash when it happens, and on Android 11+ the ANRs, native crashes and kills for
 * memory Android kept, found on the next start
 */
public final class AppExits {
    public static final String KIND_CRASH = "crash";
    public static final String KIND_APP_EXIT = "app_exit";
    public static final String KIND_ANR = "anr";
    private static final int CRASH_LOG_LINES = 60;
    private static final int MAX_EXITS = 16;
    /**
     * Apart at most: processes that went together
     */
    private static final long SAME_EXIT_MS = 5_000;
    /**
     * Of the main thread of an ANR's traces
     */
    private static final int MAX_TRACE_LINES = 30;
    private static final int MAX_TRACE_BYTES = 256 * 1024;

    private AppExits() {
    }

    /**
     * From the app's uncaught exception handler: written before it returns, with what's still in memory. Never throws.
     */
    public static void recordCrash(Context context, Thread thread, Throwable error) {
        try {
            UtubotPlayerLog.event("crash", UtubotPlayerLog.describeForCrash(error));
            FormatAttempts.flush(context, true);
            PlayerFailure.create(context, KIND_CRASH)
                    .videoId(FormatAttempts.getVideoId())
                    .error(error)
                    .detail("thread", thread.getName())
                    .detail("screen", UtubotPlayerLog.screen())
                    .detail("recentEvents", new JSONArray(UtubotPlayerLog.tail(CRASH_LOG_LINES)))
                    .recordNow();
            UtubotPlayerLog.flushNow();
        } catch (Throwable e) {
            // The crash goes on as it would
        }
    }

    /**
     * The exits since the last start (Android 11+), each once. Not on the main thread: an ANR's traces are read.
     */
    public static void recordNew(Context context) {
        if (VERSION.SDK_INT < 30) {
            return;
        }

        try {
            recordNewExits(context);
        } catch (RuntimeException e) {
            android.util.Log.e("PlayerFailure", "Can't read the app exits: " + e);
        }
    }

    @RequiresApi(30)
    private static void recordNewExits(Context context) {
        ActivityManager activityManager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);

        if (activityManager == null) {
            return;
        }

        DebuggingData debuggingData = DebuggingData.instance(context);
        long lastSeen = debuggingData.getLastAppExitTs();
        long newest = lastSeen;
        List<ApplicationExitInfo> exits = activityManager.getHistoricalProcessExitReasons(context.getPackageName(), 0, MAX_EXITS);

        // Newest first: recorded oldest first
        for (int i = exits.size() - 1; i >= 0; i--) {
            ApplicationExitInfo exit = exits.get(i);

            if (exit.getTimestamp() <= lastSeen) {
                continue;
            }

            newest = Math.max(newest, exit.getTimestamp());
            String reason = getReasonName(exit.getReason());

            // A Java crash was recorded when it happened (see recordCrash); the user closing it or the app updating isn't a failure
            if (reason == null) {
                continue;
            }

            // Android closing a cached app to make room: nobody was using it. With the low memory killer's reports, its kills are
            // low_memory ones.
            if (isReclaimed(exit) || isOfMainExit(context, exit, exits)) {
                continue;
            }

            PlayerFailure failure = PlayerFailure.create(context, KIND_APP_EXIT)
                    .at(exit.getTimestamp())
                    .withoutState()
                    .detail("reason", reason)
                    .detail("description", Scrubber.scrub(exit.getDescription()))
                    .detail("process", exit.getProcessName())
                    .detail("foreground", exit.getImportance() <= RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE)
                    // E.g. 400 cached, 125 a foreground service (background playback, the remote control)
                    .detail("importance", exit.getImportance())
                    // The signal of a "signaled" one (9: killed)
                    .detail("status", exit.getStatus())
                    // Without it the low memory killer's kills are "signaled" ones
                    .detail("lowMemoryKillReport", ActivityManager.isLowMemoryKillReportSupported())
                    .detail("pssMb", exit.getPss() / 1024)
                    .detail("rssMb", exit.getRss() / 1024);

            if (exit.getReason() == ApplicationExitInfo.REASON_ANR) {
                failure.detail("mainThread", readMainThread(exit));
            }

            // What it was doing (e.g. the remote control's service running, a video playing): Android doesn't say
            JSONObject lastState = LastState.find(context, exit.getPid(), exit.getTimestamp());

            if (lastState != null) {
                failure.detail("lastState", lastState);
            }

            failure.record();
        }

        if (newest > lastSeen) {
            debuggingData.setLastAppExitTs(newest);
        }
    }

    /**
     * A WebView's sandboxed process that went with the app's main one: one exit, recorded for the main one. Alone, its renderer failed.
     */
    @RequiresApi(30)
    private static boolean isOfMainExit(Context context, ApplicationExitInfo exit, List<ApplicationExitInfo> exits) {
        String process = exit.getProcessName();

        if (process == null || !process.contains(":sandboxed_process")) {
            return false;
        }

        for (ApplicationExitInfo other : exits) {
            if (context.getPackageName().equals(other.getProcessName()) && Math.abs(other.getTimestamp() - exit.getTimestamp()) <= SAME_EXIT_MS) {
                return true;
            }
        }

        return false;
    }

    /**
     * Android took it back while it was cached: killed by a signal, or by the low memory killer where it reports its kills
     */
    @RequiresApi(30)
    private static boolean isReclaimed(ApplicationExitInfo exit) {
        return (exit.getReason() == ApplicationExitInfo.REASON_SIGNALED || exit.getReason() == ApplicationExitInfo.REASON_LOW_MEMORY)
                && exit.getImportance() >= RunningAppProcessInfo.IMPORTANCE_CACHED;
    }

    @Nullable
    private static String getReasonName(int reason) {
        switch (reason) {
            case ApplicationExitInfo.REASON_ANR:
                return "anr";
            case ApplicationExitInfo.REASON_CRASH_NATIVE:
                return "crash_native";
            case ApplicationExitInfo.REASON_LOW_MEMORY:
                return "low_memory";
            case ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE:
                return "excessive_resource_usage";
            case ApplicationExitInfo.REASON_INITIALIZATION_FAILURE:
                return "initialization_failure";
            case ApplicationExitInfo.REASON_SIGNALED:
                return "signaled";
            default:
                return null;
        }
    }

    /**
     * The main thread's part of the traces Android took, cut short
     */
    @RequiresApi(30)
    @Nullable
    private static JSONArray readMainThread(ApplicationExitInfo exit) {
        try (InputStream traces = exit.getTraceInputStream()) {
            if (traces == null) {
                return null;
            }

            BufferedReader reader = new BufferedReader(new InputStreamReader(traces, StandardCharsets.UTF_8));
            JSONArray result = new JSONArray();
            boolean isMain = false;
            int bytes = 0;
            String line;

            while ((line = reader.readLine()) != null && bytes < MAX_TRACE_BYTES) {
                bytes += line.length() + 1;

                if (line.startsWith("\"main\"")) {
                    isMain = true;
                } else if (isMain && line.trim().isEmpty()) {
                    break;
                }

                if (isMain) {
                    result.put(Scrubber.scrub(line));

                    if (result.length() >= MAX_TRACE_LINES) {
                        break;
                    }
                }
            }

            return result.length() > 0 ? result : null;
        } catch (IOException e) {
            return null;
        }
    }
}
