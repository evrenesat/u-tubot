package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.ArrayList;
import java.util.List;

import io.reactivex.disposables.Disposable;

/**
 * Settings → Backend: the backend address, pairing, the connection test and the web admin
 */
public class UtubotBackendSettingsPresenter extends BasePresenter<Void> {
    private final UtubotSettings mSettings;
    private Disposable mAction;

    private UtubotBackendSettingsPresenter(Context context) {
        super(context);
        mSettings = UtubotSettings.instance(context);
    }

    public static UtubotBackendSettingsPresenter instance(Context context) {
        return new UtubotBackendSettingsPresenter(context);
    }

    public void show() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        for (OptionCategory category : buildCategories()) {
            dialog.appendCategory(category);
        }

        dialog.showDialog(context.getString(R.string.utubot_backend));
    }

    /**
     * The backend, always in this order: Import setup, Pair with code, Test connection, u·tubot web admin, Advanced
     */
    List<OptionCategory> buildCategories() {
        Context context = getContext();
        List<OptionCategory> categories = new ArrayList<>();

        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_import_setup),
                context.getString(R.string.utubot_import_setup_desc), option -> {
                    AppDialogPresenter.instance(context).closeDialog();
                    UtubotSetupFlow.showImportDialog(context);
                })));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_pair), context.getString(R.string.utubot_pair_desc),
                option -> {
                    AppDialogPresenter.instance(context).closeDialog();
                    UtubotPairing.showDialog(context);
                })));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_test_connection),
                context.getString(R.string.utubot_test_connection_desc), option -> testConnection())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_web_admin),
                context.getString(R.string.utubot_web_admin_desc), option -> openWebAdmin())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_advanced), context.getString(R.string.utubot_advanced_desc),
                option -> showAdvanced())));

        return categories;
    }

    private void testConnection() {
        mAction = UtubotConnectionTest.run(getContext(), mAction);
    }

    private void openWebAdmin() {
        Context context = getContext();

        if (!mSettings.isConfigured()) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_not_configured));
            return;
        }

        AppDialogPresenter.instance(context).closeDialog();
        Utils.openLink(context, mSettings.getUrl());
    }

    private void showAdvanced() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_backend_url), emptyToDash(mSettings.getUrl()),
                option -> enterUrl()));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_token),
                context.getString(mSettings.getToken().isEmpty() ? R.string.utubot_token_unset : R.string.utubot_token_set),
                option -> enterToken()));
        dialog.showDialog(context.getString(R.string.utubot_advanced));
    }

    private void enterUrl() {
        Context context = getContext();
        AppDialogPresenter.instance(context).closeDialog();
        SimpleEditDialog.showUrl(context, context.getString(R.string.utubot_backend_url), context.getString(R.string.utubot_backend_url_hint),
                mSettings.getUrl(), newValue -> {
                    try {
                        mSettings.setUrlManually(newValue);
                    } catch (UtubotSetup.SetupException e) {
                        MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_import_failed, e.getMessage()));
                        return false;
                    }
                    return true;
                });
    }

    private void enterToken() {
        Context context = getContext();
        AppDialogPresenter.instance(context).closeDialog();
        SimpleEditDialog.showPassword(context, context.getString(R.string.utubot_token), mSettings.getToken(), newValue -> {
            mSettings.setToken(newValue);
            return true;
        });
    }

    private static String emptyToDash(String text) {
        return text.isEmpty() ? "-" : text;
    }
}
