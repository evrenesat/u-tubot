package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.os.Build;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.ArrayList;
import java.util.List;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Pairing with a 6-digit code (POST /v1/pair): the token it returns is stored and the connection is tested.
 * Offered on every launch while the app is not set up or paired, until the user picks "Don't ask again".
 */
public final class UtubotPairing {
    public static final int CODE_LENGTH = 6;
    private static final int FIRST_LAUNCH_DELAY_MS = 4_000;
    private static final String TAG = "Utubot";
    private static final int HTTP_FORBIDDEN = 403;
    private static Disposable sAction;

    private UtubotPairing() {
    }

    /**
     * On every launch while the app is not set up (no backend) or not paired (no token): a choice of Import setup / Pair with code,
     * Not now, Don't ask again. Not while another dialog is open.
     */
    public static void promptIfNeeded(Context context) {
        if (context == null || !UtubotSettings.isBuiltIn()
                || !(shouldPromptSetup(UtubotSettings.instance(context)) || shouldPrompt(UtubotSettings.instance(context)))) {
            return;
        }

        Utils.postDelayed(() -> {
            UtubotSettings settings = UtubotSettings.instance(context);

            if (AppDialogPresenter.instance(context).isDialogShown()) {
                Log.d(TAG, "First launch prompt postponed: another dialog is open");
                return;
            }

            if (shouldPromptSetup(settings)) {
                Log.d(TAG, "First launch prompt: import setup");
                showPrompt(context, true);
            } else if (shouldPrompt(settings)) {
                Log.d(TAG, "First launch prompt: pairing");
                showPrompt(context, false);
            }
        }, FIRST_LAUNCH_DELAY_MS);
    }

    private static void showPrompt(Context context, boolean setup) {
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        for (OptionCategory category : buildPromptCategories(context, setup)) {
            dialog.appendCategory(category);
        }

        dialog.showDialog(context.getString(R.string.utubot_title));
    }

    static List<OptionCategory> buildPromptCategories(Context context, boolean setup) {
        UtubotSettings settings = UtubotSettings.instance(context);
        List<OptionCategory> categories = new ArrayList<>();

        categories.add(OptionCategory.singleButton(UiOptionItem.from(
                context.getString(setup ? R.string.utubot_import_setup : R.string.utubot_pair),
                context.getString(setup ? R.string.utubot_import_setup_desc : R.string.utubot_pair_desc),
                option -> {
                    AppDialogPresenter.instance(context).closeDialog();

                    if (setup) {
                        UtubotSetupFlow.showImportDialog(context);
                    } else {
                        showDialog(context);
                    }
                })));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_not_now),
                context.getString(R.string.utubot_not_now_desc), option -> AppDialogPresenter.instance(context).closeDialog())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_dont_ask),
                context.getString(R.string.utubot_dont_ask_desc), option -> {
                    Log.d(TAG, "First launch prompt: don't ask again");
                    if (setup) {
                        settings.setSetupPromptDone(true);
                    } else {
                        settings.setPairPromptDone(true);
                    }
                    AppDialogPresenter.instance(context).closeDialog();
                })));

        return categories;
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
        Log.d(TAG, "Pairing with %s", client.getBaseUrl());
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_pairing));
        RxHelper.disposeActions(sAction);
        sAction = Observable.fromCallable(() -> client.pair(code, Build.MODEL))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(result -> {
                            Log.d(TAG, "Pairing ok: user %s", result.user);
                            settings.setToken(result.token);
                            settings.setPairPromptDone(true);
                            UtubotSetupFlow.importPendingPromptSets(context);
                            verify(context, result.user);
                        },
                        error -> {
                            Log.e(TAG, "Pairing failed: %s: %s", error.getClass().getSimpleName(), error.getMessage());
                            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_pair_failed, describePairError(context, error)));
                        });
    }

    static String describePairError(Context context, Throwable error) {
        if (error instanceof UtubotClient.HttpException && ((UtubotClient.HttpException) error).code == HTTP_FORBIDDEN) {
            return context.getString(R.string.utubot_pair_wrong_code);
        }

        return UtubotSetupFlow.describeError(context, error);
    }

    /**
     * The connection test after the pairing; "Paired as <user>" once the stored token works
     */
    private static void verify(Context context, String pairedUser) {
        UtubotClient client = UtubotManager.instance(context).newClient();
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_testing));
        sAction = Observable.fromCallable(() -> {
                    client.health();
                    return client.me();
                })
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(me -> {
                            Log.d(TAG, "Connection test after pairing ok");
                            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_paired, me.user == null || me.user.isEmpty() ? pairedUser : me.user));
                        },
                        error -> {
                            Log.e(TAG, "Connection test after pairing failed: %s: %s", error.getClass().getSimpleName(), error.getMessage());
                            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_paired_test_failed, pairedUser,
                                    UtubotSetupFlow.describeError(context, error)));
                        });
    }
}
