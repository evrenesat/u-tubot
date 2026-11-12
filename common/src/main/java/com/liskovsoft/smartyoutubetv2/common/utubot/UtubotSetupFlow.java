package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;

import java.util.List;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Import setup: the user types a short address, the app fetches its /setup.json, stores it and goes straight to the pairing dialog.
 */
public final class UtubotSetupFlow {
    private static Disposable sAction;

    private UtubotSetupFlow() {
    }

    public static void showImportDialog(Context context) {
        SimpleEditDialog.showUrl(context, context.getString(R.string.utubot_import_setup), context.getString(R.string.utubot_import_setup_hint),
                "", address -> {
                    importFrom(context, address);
                    return true;
                });
    }

    static void importFrom(Context context, String address) {
        String url;

        try {
            url = UtubotSetup.resolveUrl(address);
        } catch (UtubotSetup.SetupException e) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_import_failed, e.getMessage()));
            return;
        }

        MessageHelpers.showMessage(context, context.getString(R.string.utubot_importing));
        RxHelper.disposeActions(sAction);
        sAction = Observable.fromCallable(() -> UtubotClient.fetchSetup(url))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(setup -> apply(context, setup),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_import_failed, error.getMessage())));
    }

    private static void apply(Context context, UtubotSetup setup) {
        UtubotSettings.instance(context).applySetup(setup);
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_import_ok, setup.name.isEmpty() ? setup.backendUrl : setup.name));

        if (setup.pairing && UtubotSettings.instance(context).getToken().isEmpty()) {
            UtubotPairing.showDialog(context);
        }
    }

    /**
     * Imports the prompt sets the setup listed, after the pairing gave a token. A failing one doesn't stop the rest.
     */
    static void importPendingPromptSets(Context context) {
        List<String> urls = UtubotSettings.instance(context).takePendingPromptSets();
        UtubotManager manager = UtubotManager.instance(context);

        for (String url : urls) {
            manager.importPromptsObserve(url).subscribe(done -> { }, error -> { });
        }
    }
}
