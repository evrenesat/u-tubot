package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.net.Uri;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.List;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * "u·tubot web admin": ask the backend for a short-lived, single-use sign-in link for the paired
 * device and open it in the system browser (Intent.ACTION_VIEW). The browser handles the login
 * form's input quirks. When no browser is installed, the link is shown as a QR code to scan on
 * another device: the fallback the issue keeps.
 */
public final class UtubotWebAdmin {
    private static final String TAG = "Utubot";
    private static final String WEB_LOGIN_PATH = "/web-login/";
    private static final String BROWSABLE_URL = "https://www.example.com/";
    private static Disposable sAction;

    private UtubotWebAdmin() {
    }

    /**
     * The sign-in link the device opens: the backend address plus the one-time token path. Extracted
     * so the URL is unit tested without the network or the framework.
     */
    static String loginUrl(String baseUrl, String token) {
        return stripTrailingSlash(baseUrl) + WEB_LOGIN_PATH + token;
    }

    /**
     * Open the web admin: guard on pairing (local, no backend call), fetch a link, then open it in a
     * browser or fall back to a QR code.
     */
    public static void open(final Context context) {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        final UtubotSettings settings = UtubotSettings.instance(context);
        if (!settings.isConfigured() || settings.getToken().isEmpty()) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_web_admin_unpaired));
            return;
        }

        final UtubotClient client = UtubotManager.instance(context).newClient();
        RxHelper.disposeActions(sAction);
        MessageHelpers.showMessage(context, context.getString(R.string.utubot_web_admin_opening));
        sAction = Observable.fromCallable(() -> client.webLogin())
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(result -> openLink(context, client.getBaseUrl(), result.token), error -> {
                    Log.e(TAG, "Web admin failed: %s: %s", error.getClass().getSimpleName(), error.getMessage());
                    MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_web_admin_failed,
                            error.getMessage() != null ? error.getMessage() : context.getString(R.string.utubot_web_admin_opening)));
                });
    }

    /**
     * A link is ready: open it in the system browser, or show it as a QR code when no browser can.
     * The QR is only reached when the browser check fails or nothing can handle the link.
     */
    static void openLink(Context context, String baseUrl, String token) {
        final String url = loginUrl(baseUrl, token);

        if (hasBrowser(context)) {
            try {
                context.startActivity(viewIntent(context, url));
                return;
            } catch (android.content.ActivityNotFoundException e) {
                Log.d(TAG, "No activity can open the sign-in link; showing the QR");
            }
        }

        UtubotCutQrView.show(context, url, context.getString(R.string.utubot_web_admin_qr_hint));
    }

    /**
     * True when a browser that can open an https URL is installed. The recommended BROWSABLE check:
     * a browser declares the BROWSABLE category for an http(s) filter, a plain share app does not.
     */
    static boolean hasBrowser(Context context) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(BROWSABLE_URL));
        intent.addCategory(Intent.CATEGORY_BROWSABLE);
        List<ResolveInfo> matches = context.getPackageManager().queryIntentActivities(intent, 0);
        for (ResolveInfo match : matches) {
            if (match.activityInfo != null && match.activityInfo.packageName != null) {
                return true;
            }
        }
        return false;
    }

    /**
     * Opens a page of the backend in the system browser (a chooser when nothing claims it); the touch sheets use it.
     */
    static void openInBrowser(Context context, String url) {
        try {
            context.startActivity(viewIntent(context, url));
        } catch (android.content.ActivityNotFoundException e) {
            Utils.showMultiChooser(context, Uri.parse(url));
        }
    }

    private static Intent viewIntent(Context context, String url) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        if (!(context instanceof Activity)) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        }
        return intent;
    }

    private static String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
