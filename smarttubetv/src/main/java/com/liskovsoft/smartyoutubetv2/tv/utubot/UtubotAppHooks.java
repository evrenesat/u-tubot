package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.app.Application;
import android.os.Bundle;

import com.liskovsoft.smartyoutubetv2.common.diagnostics.AnrWatchdog;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.ReportUploader;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutNotices;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotScreen;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettingsSyncRunner;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotUiHost;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotUpdates;
import com.liskovsoft.smartyoutubetv2.tv.ui.dialogs.AppDialogActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.playback.PlaybackActivity;

import java.util.Map;
import java.util.WeakHashMap;

/**
 * App-wide u-tubot hooks, installed with one call from MainApplication: the working badge (see UtubotBadgeController) on every screen
 * but the player, which keeps its picture clear, and which kind of screen is up, for the video menu (see UtubotUiHost).
 */
public final class UtubotAppHooks {
    private UtubotAppHooks() {
    }

    public static void install(Application application) {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        UtubotCutNotices.instance(application).install();
        // Crash reports and the player's event log, sent to the backend while nothing plays (see ReportUploader)
        UtubotPlayerLog.init(application);
        AnrWatchdog.start(application);
        ReportUploader.start(application);

        application.registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            // The controller holds its activity weakly: a value that held its key would keep the entry from ever being collected
            private final Map<Activity, UtubotBadgeController> mControllers = new WeakHashMap<>();

            @Override
            public void onActivityResumed(Activity activity) {
                UtubotPlayerLog.setScreen(activity.getClass().getSimpleName());
                UtubotPlayerLog.event("activity.resumed", activity.getClass().getSimpleName());
                boolean isDialog = activity instanceof AppDialogActivity;
                UtubotScreen.onResumed(activity, isDialog);

                if (!isDialog) {
                    UtubotUiHost.setPlayerScreen(activity instanceof PlaybackActivity);

                    if (!(activity instanceof PlaybackActivity)) {
                        // The player closed or the app came back: an update that was found meanwhile is offered now
                        UtubotUpdates.onScreenAvailable();
                        UtubotSettingsSyncRunner.requestNow(activity);
                    }

                    // A cut or its failure that arrived while no screen was up is shown on this one
                    UtubotCutNotices.instance(activity).onScreenAvailable();
                }

                if (activity instanceof PlaybackActivity) {
                    return;
                }

                UtubotBadgeController controller = mControllers.get(activity);

                if (controller == null) {
                    controller = new UtubotBadgeController(activity);
                    mControllers.put(activity, controller);
                }

                controller.onResume();
            }

            @Override
            public void onActivityPaused(Activity activity) {
                UtubotPlayerLog.event("activity.paused", activity.getClass().getSimpleName());

                if (activity instanceof PlaybackActivity) {
                    UtubotPlayerLog.flushAsync();
                }

                UtubotScreen.onPaused(activity);

                UtubotBadgeController controller = mControllers.get(activity);

                if (controller != null) {
                    controller.onPause();
                }
            }

            @Override
            public void onActivityDestroyed(Activity activity) {
                UtubotPlayerLog.event("activity.destroyed", activity.getClass().getSimpleName());

                if (activity instanceof PlaybackActivity) {
                    UtubotPlayerLog.flushAsync();
                    ReportUploader.onPlaybackEnded();
                }

                UtubotScreen.onPaused(activity);
                UtubotBadgeController controller = mControllers.remove(activity);

                if (controller != null) {
                    controller.onDestroy();
                }
            }

            @Override
            public void onActivityCreated(Activity activity, Bundle savedInstanceState) {
                UtubotPlayerLog.event("activity.created", activity.getClass().getSimpleName());
            }

            @Override
            public void onActivityStarted(Activity activity) {
            }

            @Override
            public void onActivityStopped(Activity activity) {
                UtubotPlayerLog.event("activity.stopped", activity.getClass().getSimpleName());

                if (activity instanceof PlaybackActivity) {
                    UtubotPlayerLog.flushAsync();
                }
            }

            @Override
            public void onActivitySaveInstanceState(Activity activity, Bundle outState) {
            }
        });
    }
}
