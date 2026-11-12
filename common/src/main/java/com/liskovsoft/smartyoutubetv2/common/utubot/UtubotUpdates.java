package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.AppUpdatePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.ViewManager;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

/**
 * The automatic update check of the built-in flavor: it runs Electric Eel's update flow (AppUpdatePresenter: version check against
 * the stored update URL, download of the APK of the device's ABI, the update dialog with the changelog, the installer) after the
 * app starts and every {@link UtubotUpdateSchedule#INTERVAL_MS}.
 */
public final class UtubotUpdates {
    private static final String TAG = UtubotUpdates.class.getSimpleName();
    @SuppressLint("StaticFieldLeak")
    private static UtubotUpdateSchedule sSchedule;

    private UtubotUpdates() {
    }

    /**
     * Starts the schedule, once. Nothing in the other flavors.
     */
    public static synchronized void start(Context context) {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        if (sSchedule == null) {
            Context appContext = context.getApplicationContext();
            sSchedule = new UtubotUpdateSchedule(UtubotScheduler.mainThread(), () -> check(appContext));
        }

        sSchedule.start();
    }

    /**
     * Replaces the schedule (null: none), for tests
     */
    static synchronized void useSchedule(UtubotUpdateSchedule schedule) {
        sSchedule = schedule;
    }

    /**
     * An update was found and could not be shown (the player is open, the app is in the background): it is offered again soon,
     * not at the next 6 hour check.
     */
    public static synchronized void onUpdateDeferred() {
        if (sSchedule != null) {
            Log.d(TAG, "An update is waiting for a screen to show it");
            sSchedule.onUpdateDeferred();
        }
    }

    /**
     * A screen that can show the update dialog is up (the player closed, the app came back to the front)
     */
    public static synchronized void onScreenAvailable() {
        if (sSchedule != null) {
            sSchedule.onScreenAvailable();
        }
    }

    private static boolean check(Context appContext) {
        if (UtubotSettings.instance(appContext).getUpdateUrl().isEmpty()) {
            return false;
        }

        ViewManager viewManager = ViewManager.instance(appContext);

        // The update dialog is shown only over the browse screens
        if (!Utils.isAppInForegroundFixed() || viewManager.isPlayerInForeground() || AppDialogPresenter.instance(appContext).isDialogShown()) {
            return false;
        }

        Log.d(TAG, "Checking for updates");
        AppUpdatePresenter.instance(BrowsePresenter.instance(appContext).getContext()).start(false);

        return true;
    }
}
