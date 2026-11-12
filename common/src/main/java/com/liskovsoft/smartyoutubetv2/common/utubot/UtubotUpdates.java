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
