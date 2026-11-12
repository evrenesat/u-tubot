package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs;

import android.annotation.SuppressLint;
import android.content.Context;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotUpdates;

/**
 * Shows boot dialogs one by one.
 */
public class BootDialogPresenter extends BasePresenter<Void> {
    @SuppressLint("StaticFieldLeak")
    private static BootDialogPresenter sInstance;

    public BootDialogPresenter(Context context) {
        super(context);
    }

    public static BootDialogPresenter instance(Context context) {
        if (sInstance == null) {
            sInstance = new BootDialogPresenter(context);
        }

        sInstance.setContext(context);

        return sInstance;
    }

    //public void unhold() {
    //    sInstance = null;
    //}

    public void start() {
        startUpdatePresenter();
    }

    private void startUpdatePresenter() {
        // u-tubot: a delayed check, then one every few hours while the app runs
        if (UtubotSettings.isBuiltIn()) {
            UtubotUpdates.start(getContext());
            return;
        }

        AppUpdatePresenter updatePresenter = AppUpdatePresenter.instance(getContext());
        //updatePresenter.setOnDone(this::startBridgePresenter);
        updatePresenter.start(false);
        //updatePresenter.unhold();
    }

    //private void startBackupPresenter() {
    //    QuickRestorePresenter quickRestorePresenter = QuickRestorePresenter.instance(getContext());
    //    quickRestorePresenter.setOnDone(this::startBridgePresenter);
    //    quickRestorePresenter.start();
    //    quickRestorePresenter.unhold();
    //}

    //private void startBridgePresenter() {
    //    ATVBridgePresenter atvPresenter = ATVBridgePresenter.instance(getContext());
    //    atvPresenter.start();
    //    atvPresenter.unhold();
    //
    //    AmazonBridgePresenter amazonPresenter = AmazonBridgePresenter.instance(getContext());
    //    amazonPresenter.start();
    //    amazonPresenter.unhold();
    //}
}
