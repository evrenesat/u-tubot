package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.AppInfoHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.List;
import java.util.TimeZone;

import io.reactivex.Observable;
import io.reactivex.schedulers.Schedulers;

/**
 * "What's new in X", once after the app was updated: the notes of the installed version, fetched from the backend and shown as
 * text. A fresh install shows nothing (it has no previous version to compare with).
 */
public final class UtubotWhatsNew {
    private static final String TAG = UtubotWhatsNew.class.getSimpleName();
    private static final String PREFS = "utubot_whats_new";
    private static final String KEY_SEEN_VERSION = "seen_version";
    private static boolean sIsLoading;

    private UtubotWhatsNew() {
    }

    /**
     * Whether the installed version is new to the user: it differs from the one the notes were last offered for
     *
     * @param seen empty on a fresh install
     */
    static boolean isPending(@Nullable String seen, @Nullable String installed) {
        return seen != null && !seen.isEmpty() && installed != null && !installed.isEmpty() && !seen.equals(installed);
    }

    /**
     * Offers the notes of an update that has not been offered yet, in the background. Call it where a dialog can be shown.
     *
     * @return true when an offer was started or is under way: the caller leaves the screen alone for now
     */
    @SuppressLint("CheckResult")
    public static synchronized boolean offerIfUpdated(Context context) {
        Context appContext = context.getApplicationContext();
        String installed = AppInfoHelpers.getAppVersionName(appContext);
        SharedPreferences prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String seen = prefs.getString(KEY_SEEN_VERSION, "");

        if (seen.isEmpty()) {
            prefs.edit().putString(KEY_SEEN_VERSION, installed).apply();
            return false;
        }

        if (!isPending(seen, installed)) {
            return false;
        }

        if (sIsLoading) {
            return true;
        }

        sIsLoading = true;
        Observable.fromCallable(() -> UtubotChangelog.parse(UtubotManager.instance(appContext).newClient().changelogJson(UtubotChangelog.KIND_APP)))
                .subscribeOn(Schedulers.io())
                .subscribe(entries -> Utils.post(() -> show(appContext, installed, entries)), error -> {
                    // Not marked as seen: it is offered again at the next check
                    Log.e(TAG, "The notes of %s could not be loaded: %s", installed, error.getMessage());
                    sIsLoading = false;
                });

        return true;
    }

    private static void show(Context context, String installed, List<UtubotChangelog.Entry> entries) {
        sIsLoading = false;
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_SEEN_VERSION, installed).apply();
        UtubotChangelog.Entry entry = UtubotChangelog.find(entries, installed);

        if (entry == null) {
            return;
        }

        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        String title = context.getString(R.string.utubot_whats_new_in, installed);
        dialog.appendLongTextCategory(title, UiOptionItem.from(UtubotChangelog.text(entry, TimeZone.getDefault(),
                context.getString(R.string.utubot_whats_new_no_changes))), false);
        dialog.showDialog(title);
    }
}
