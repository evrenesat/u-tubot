package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;

import androidx.annotation.Nullable;

import java.lang.ref.WeakReference;
import java.util.Collections;
import java.util.Set;
import java.util.WeakHashMap;

/**
 * Which activity screens are up, for the app-wide cut pop-up (issue 96): a question is only asked while somebody is looking at the app,
 * and its dialog goes over the screen that is up (the player included, without pausing it).
 */
public final class UtubotScreen {
    private static final Set<Activity> sResumed = Collections.newSetFromMap(new WeakHashMap<Activity, Boolean>());
    private static WeakReference<Activity> sScreen = new WeakReference<>(null);

    private UtubotScreen() {
    }

    public static void onResumed(Activity activity, boolean isDialog) {
        synchronized (sResumed) {
            sResumed.add(activity);

            if (!isDialog) {
                sScreen = new WeakReference<>(activity);
            }
        }
    }

    public static void onPaused(Activity activity) {
        synchronized (sResumed) {
            sResumed.remove(activity);
        }
    }

    /**
     * At least one of the app's activities is resumed: the viewer is looking at the app, not at the home screen or another app
     */
    public static boolean isForeground() {
        synchronized (sResumed) {
            return !sResumed.isEmpty();
        }
    }

    /**
     * The activity to open a dialog with: the last screen that is not a dialog, else the one that is up
     */
    @Nullable
    public static Context screenContext() {
        synchronized (sResumed) {
            Activity screen = sScreen.get();

            if (screen != null && sResumed.contains(screen)) {
                return screen;
            }

            for (Activity activity : sResumed) {
                return activity;
            }

            return null;
        }
    }
}
