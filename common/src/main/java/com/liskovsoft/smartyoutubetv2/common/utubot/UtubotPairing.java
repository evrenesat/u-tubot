package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.os.Build;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Pairing with a 6-digit code (POST /v1/pair): the token it returns is stored and the connection is tested.
 * Offered once on the first launch while no token is set (after the setup import, which comes first without a backend).
 */
public final class UtubotPairing {
    public static final int CODE_LENGTH = 6;
    private static final int FIRST_LAUNCH_DELAY_MS = 4_000;
    private static Disposable sAction;

    private UtubotPairing() {
    }

    /**
     * On the first launch without a token: the pairing dialog, unless another dialog is open (it comes back with the next launch)
     */
    public static void promptIfNeeded(Context context) {
        if (context == null || !UtubotSettings.isBuiltIn()
                || !(shouldPromptSetup(UtubotSettings.instance(context)) || shouldPrompt(UtubotSettings.instance(context)))) {
            return;
        }

        Utils.postDelayed(() -> {
            UtubotSettings settings = UtubotSettings.instance(context);

            if (AppDialogPresenter.instance(context).isDialogShown()) {
                return;
            }

            if (shouldPromptSetup(settings)) {
                settings.setSetupPromptDone(true);
                UtubotSetupFlow.showImportDialog(context);
            } else if (shouldPrompt(settings)) {
                settings.setPairPromptDone(true);
                showDialog(context);
            }
        }, FIRST_LAUNCH_DELAY_MS);
    }

    /**
     * First launch with no backend: offer the setup import (skippable), then the pairing follows from it
     */
    static boolean shouldPromptSetup(UtubotSettings settings) {
        return UtubotSettings.isBuiltIn() && !settings.isConfigured() && !settings.isSetupPromptDone();
    }

    static boolean shouldPrompt(UtubotSettings settings) {
        return settings.isConfigured() && settings.getToken().isEmpty() && !settings.isPairPromptDone();
    }

    public static boolean isValidCode(String code) {
        return code != null && code.trim().matches("\\d{" + CODE_LENGTH + "}");
    }

    public static void showDialog(Context context) {
        SimpleEditDialog.showNumber(context, context.getString(R.string.utubot_pair), context.getString(R.string.utubot_pair_hint), code -> {
            if (!isValidCode(code)) {
                MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_pair_invalid, CODE_LENGTH));
                return false;
            }

            pair(context, code.trim());
            return true;
        }, null);
    }

    static void pair(Context context, String code) {
        UtubotSettings settings = UtubotSettings.instance(context);
        UtubotClient client = UtubotManager.instance(context).newClient();
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_pairing));
        RxHelper.disposeActions(sAction);
        sAction = Observable.fromCallable(() -> client.pair(code, Build.MODEL))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(result -> {
                            settings.setToken(result.token);
                            settings.setPairPromptDone(true);
                            MessageHelpers.showMessage(context, context.getString(R.string.utubot_paired, result.user));
                            UtubotSetupFlow.importPendingPromptSets(context);
                            sAction = UtubotConnectionTest.run(context, null);
                        },
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_pair_failed, error.getMessage())));
    }
}
