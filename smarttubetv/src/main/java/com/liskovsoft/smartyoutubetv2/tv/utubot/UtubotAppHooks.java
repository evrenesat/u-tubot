package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.app.Application;
import android.os.Bundle;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotUiHost;
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

        application.registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            private final Map<Activity, UtubotBadgeController> mControllers = new WeakHashMap<>();

            @Override
            public void onActivityResumed(Activity activity) {
                if (!(activity instanceof AppDialogActivity)) {
                    UtubotUiHost.setPlayerScreen(activity instanceof PlaybackActivity);
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
                UtubotBadgeController controller = mControllers.get(activity);

                if (controller != null) {
                    controller.onPause();
                }
            }

            @Override
            public void onActivityDestroyed(Activity activity) {
                UtubotBadgeController controller = mControllers.remove(activity);

                if (controller != null) {
                    controller.onDestroy();
                }
            }

            @Override
            public void onActivityCreated(Activity activity, Bundle savedInstanceState) {
            }

            @Override
            public void onActivityStarted(Activity activity) {
            }

            @Override
            public void onActivityStopped(Activity activity) {
            }

            @Override
            public void onActivitySaveInstanceState(Activity activity, Bundle outState) {
            }
        });
    }
}
