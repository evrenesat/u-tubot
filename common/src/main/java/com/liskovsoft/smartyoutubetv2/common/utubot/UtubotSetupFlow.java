package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;

import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.List;

import javax.net.ssl.SSLException;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Import setup: the user types a short address, the app fetches its /setup.json, stores it and goes straight to the pairing dialog.
 */
public final class UtubotSetupFlow {
    private static final String TAG = "Utubot";
    private static Disposable sAction;

    private UtubotSetupFlow() {
    }

    public static void showImportDialog(Context context) {
        Log.d(TAG, "Import setup dialog opened");
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
            Log.d(TAG, "Import setup: bad address (%s)", e.getMessage());
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_import_failed, e.getMessage()));
            return;
        }

        Log.d(TAG, "Import setup: fetching %s", withoutQuery(url));
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_importing));
        RxHelper.disposeActions(sAction);
        sAction = Observable.fromCallable(() -> UtubotClient.fetchSetup(url))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(setup -> apply(context, setup),
                        error -> {
                            Log.e(TAG, "Import setup failed: %s: %s", error.getClass().getSimpleName(), error.getMessage());
                            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_import_failed, describeError(context, error)));
                        });
    }

    /**
     * scheme://host[:port]/path of an address: the query may carry a secret
     */
    static String withoutQuery(String url) {
        try {
            java.net.URI uri = new java.net.URI(url);
            return new java.net.URI(uri.getScheme(), uri.getRawAuthority(), uri.getPath(), null, null).toString();
        } catch (java.net.URISyntaxException e) {
            int cut = url.indexOf('?');
            return cut >= 0 ? url.substring(0, cut) : url;
        }
    }

    /**
     * The reason of a failed import in words: DNS, TLS, timeout, connection, HTTP status or a bad setup file
     */
    static String describeError(Context context, Throwable error) {
        if (error instanceof UtubotSetup.SetupException) {
            return error.getMessage();
        }
        if (error instanceof UtubotClient.HttpException) {
            return context.getString(R.string.utubot_error_http, ((UtubotClient.HttpException) error).code);
        }
        if (error instanceof UnknownHostException) {
            return context.getString(R.string.utubot_error_dns);
        }
        if (error instanceof SSLException) {
            return context.getString(R.string.utubot_error_tls);
        }
        if (error instanceof SocketTimeoutException) {
            return context.getString(R.string.utubot_error_timeout);
        }
        if (error instanceof ConnectException || error instanceof NoRouteToHostException) {
            return context.getString(R.string.utubot_error_connect);
        }

        String message = error.getMessage();

        return message == null || message.isEmpty() ? error.getClass().getSimpleName() : message;
    }

    private static void apply(Context context, UtubotSetup setup) {
        UtubotSettings settings = UtubotSettings.instance(context);
        boolean needsPairing = settings.applySetup(setup);
        String name = setup.name.isEmpty() ? setup.backendUrl : setup.name;
        Log.d(TAG, "Import setup ok: server %s, pairing %s", name, setup.pairing);
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_import_ok, name));

        if (setup.pairing && needsPairing) {
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
