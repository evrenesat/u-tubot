package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Settings → u·tubot → Test connection: /v1/health, then /v1/me, the result shown as a message
 */
public final class UtubotConnectionTest {
    private UtubotConnectionTest() {
    }

    /**
     * @param previous an earlier run, cancelled
     * @return the running test
     */
    public static Disposable run(Context context, @Nullable Disposable previous) {
        UtubotSettings settings = UtubotSettings.instance(context);

        if (!settings.isConfigured()) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_not_configured));
            return null;
        }

        MessageHelpers.showMessage(context, context.getString(R.string.utubot_testing));
        UtubotClient client = UtubotManager.instance(context).newClient();
        RxHelper.disposeActions(previous);
        return Observable.fromCallable(() -> test(context, client))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(message -> MessageHelpers.showLongMessage(context, message),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_test_failed, error.getMessage())));
    }

    static String test(Context context, UtubotClient client) throws Exception {
        client.health();

        try {
            Me me = client.me();
            return context.getString(R.string.utubot_test_ok, client.getBaseUrl(), me.user);
        } catch (UtubotClient.HttpException e) {
            if (e.isUnauthorized()) {
                return context.getString(R.string.utubot_test_unauthorized);
            }

            throw e;
        }
    }
}
