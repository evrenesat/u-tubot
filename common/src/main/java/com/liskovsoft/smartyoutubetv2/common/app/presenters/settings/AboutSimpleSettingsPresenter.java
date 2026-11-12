package com.liskovsoft.smartyoutubetv2.common.app.presenters.settings;

import android.content.Context;
import android.text.TextUtils;
import com.liskovsoft.sharedutils.helpers.AppInfoHelpers;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettingsPresenter;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;

public class AboutSimpleSettingsPresenter extends BasePresenter<Void> {
    public AboutSimpleSettingsPresenter(Context context) {
        super(context);
    }

    public static AboutSimpleSettingsPresenter instance(Context context) {
        return new AboutSimpleSettingsPresenter(context);
    }

    /**
     * The updates are in Updates and the global search in Search|General
     */
    public void show() {
        String versionName = AppInfoHelpers.getAppVersionName(getContext());
        String mainTitle = String.format("%s %s", getContext().getString(R.string.app_name), versionName);

        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendServer(settingsPresenter);

        // In the order of the full About
        appendQrCode(settingsPresenter, R.string.donation, R.string.about_donation_url);
        appendQrCode(settingsPresenter, R.string.feedback, R.string.about_feedback_url);
        appendQrCode(settingsPresenter, R.string.releases, R.string.about_releases_url);
        appendQrCode(settingsPresenter, R.string.git_repository, R.string.about_git_repository_url);
        appendCredit(settingsPresenter);

        settingsPresenter.showDialog(mainTitle);
    }

    /**
     * Where the app's backend is: its address (a QR code of it, e.g. for the web UI), or "Not set up" (the setup is offered)
     */
    private void appendServer(AppDialogPresenter settingsPresenter) {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        String title = getContext().getString(R.string.about_server);
        String url = UtubotSettings.instance(getContext()).getUrl();

        if (TextUtils.isEmpty(url)) {
            settingsPresenter.appendSingleButton(UiOptionItem.from(title, getContext().getString(R.string.about_server_not_set),
                    option -> UtubotSettingsPresenter.instance(getContext()).show()));
        } else {
            settingsPresenter.appendSingleButton(UiOptionItem.from(title, url, option -> showQrCode(title, url)));
        }
    }

    /**
     * A row that opens a panel with a QR code of the address. No address (the flavor has none), no row.
     */
    private void appendQrCode(AppDialogPresenter settingsPresenter, int titleResId, int urlResId) {
        String url = getContext().getString(urlResId);

        if (TextUtils.isEmpty(url)) {
            return;
        }

        String title = getContext().getString(titleResId);

        settingsPresenter.appendSingleButton(UiOptionItem.from(title, option -> showQrCode(title, url)));
    }

    /**
     * The projects the app is based on, one row for them all: each opens a panel with a QR code of its repository
     */
    private void appendCredit(AppDialogPresenter settingsPresenter) {
        String title = getContext().getString(R.string.about_credit);
        Map<String, String> credits = Helpers.getMap(getContext(), R.array.about_credits);

        if (TextUtils.isEmpty(title) || credits.isEmpty()) {
            return;
        }

        List<OptionItem> options = new ArrayList<>();

        for (Entry<String, String> credit : credits.entrySet()) {
            options.add(UiOptionItem.from(credit.getKey(), option -> showQrCode(credit.getKey(), credit.getValue())));
        }

        settingsPresenter.appendStringsCategory(title, options);
    }

    /**
     * The code has the address, so it isn't written out. Made on the device: it's there when the panel opens.
     */
    private void showQrCode(String title, String url) {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        settingsPresenter.appendQrCode(title, url);

        // A single item would be opened right away instead of showing the panel with the picture
        settingsPresenter.enableExpandable(false);
        settingsPresenter.showDialog(title);
    }
}
