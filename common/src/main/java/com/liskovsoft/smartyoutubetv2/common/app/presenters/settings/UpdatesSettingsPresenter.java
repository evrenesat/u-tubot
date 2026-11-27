package com.liskovsoft.smartyoutubetv2.common.app.presenters.settings;

import android.content.Context;
import android.text.Html;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.StyleSpan;
import android.graphics.Typeface;

import androidx.annotation.Nullable;
import androidx.webkit.WebViewCompat;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.sharedutils.helpers.AppInfoHelpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.QrCodePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.ReleaseNotesPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.AppUpdatePresenter;
import com.liskovsoft.smartyoutubetv2.common.misc.GitHubReleases;
import com.liskovsoft.smartyoutubetv2.common.misc.GitHubReleases.Release;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotChangelog;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotClient;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotChangelog.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsDeveloperPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.ArrayList;
import java.util.List;
import java.util.TimeZone;

import io.reactivex.Observable;
import io.reactivex.disposables.Disposable;

/**
 * The Updates section of the settings (was in About)
 */
public class UpdatesSettingsPresenter extends BasePresenter<Void> {
    /**
     * Of every panel: a second press while the list loads is ignored
     */
    private static Disposable sReleasesAction;
    private final AppUpdateChecker mUpdateChecker;
    /**
     * Of the panel as the settings opened it, e.g. "Updates - Release notes": the same when it's opened again after the notes
     */
    private boolean mIsNestedTitles;
    private final UtubotSettings mSettings;

    private UpdatesSettingsPresenter(Context context) {
        super(context);

        mUpdateChecker = new AppUpdateChecker(getContext(), null);
        mSettings = UtubotSettings.instance(context);
    }

    public static UpdatesSettingsPresenter instance(Context context) {
        return new UpdatesSettingsPresenter(context);
    }

    public void show() {
        show(false);
    }

    /**
     * @param isReleaseNotesFocused its row has the focus, as when the list was opened from it (e.g. back from the notes)
     */
    private void show(boolean isReleaseNotesFocused) {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        settingsPresenter.appendSingleSwitch(UiOptionItem.from(getContext().getString(R.string.check_updates_auto),
                optionItem -> mUpdateChecker.setUpdateCheckEnabled(optionItem.isSelected()),
                mUpdateChecker.isUpdateCheckEnabled()));

        settingsPresenter.appendSingleButton(UiOptionItem.from(getContext().getString(R.string.check_for_updates),
                option -> AppUpdatePresenter.instance(getContext()).start(true)));

        if (UtubotSettings.isBuiltIn()) {
            settingsPresenter.appendSingleButton(UiOptionItem.from(getContext().getString(R.string.utubot_whats_new), option -> loadChangelogs()));
            settingsPresenter.appendSingleButton(UiOptionItem.from(getContext().getString(R.string.utubot_update_interval),
                    UtubotSettings.formatBrowseRefresh(getContext(), mSettings.getUpdateIntervalMinutes()), option -> showUpdateInterval()));
            settingsPresenter.appendSingleSwitch(UiOptionItem.from(getContext().getString(R.string.utubot_development_mode),
                    getContext().getString(R.string.utubot_development_mode_desc),
                    option -> mSettings.setDevelopmentMode(option.isSelected()), mSettings.isDevelopmentMode()));
            settingsPresenter.appendSingleSwitch(UiOptionItem.from(getContext().getString(R.string.utubot_films_developer),
                    getContext().getString(R.string.utubot_films_developer_desc),
                    option -> {
                        mSettings.setFilmsDeveloperEnabled(option.isSelected());
                        settingsPresenter.closeDialog();
                        show();
                    }, mSettings.isFilmsDeveloperEnabled()));

            if (mSettings.isFilmsDeveloperEnabled()) {
                settingsPresenter.appendSingleButton(UiOptionItem.from(getContext().getString(R.string.utubot_films_open),
                        option -> UtubotFilmsDeveloperPresenter.instance(getContext()).show()));
            }
        }

        OptionItem releaseNotesItem = UiOptionItem.from(getContext().getString(R.string.release_notes), option -> loadReleases());
        settingsPresenter.appendSingleButton(releaseNotesItem);

        if (isReleaseNotesFocused) {
            settingsPresenter.setFocusedItem(releaseNotesItem);
        }

        settingsPresenter.showDialog(getContext().getString(R.string.settings_updates));
        mIsNestedTitles = settingsPresenter.isNestedTitlesEnabled();
    }

    private void showUpdateInterval() {
        AppDialogPresenter dialog = AppDialogPresenter.instance(getContext());
        List<OptionItem> options = new ArrayList<>();

        for (int minutes : UtubotSettings.UPDATE_INTERVAL_CHOICES_MINUTES) {
            options.add(UiOptionItem.from(UtubotSettings.formatBrowseRefresh(getContext(), minutes), option -> mSettings.setUpdateIntervalMinutes(minutes),
                    minutes == mSettings.getUpdateIntervalMinutes()));
        }

        dialog.appendRadioCategory(getContext().getString(R.string.utubot_update_interval), options);
        dialog.showDialog(getContext().getString(R.string.utubot_update_interval));
    }

    private void loadReleases() {
        if (RxHelper.isAnyActionRunning(sReleasesAction)) {
            return;
        }

        sReleasesAction = RxHelper.execute(GitHubReleases.latestObserve(getContext(), getChangelogFallbackUrl()), releases -> showReleases(releases, null),
                error -> {
                    Context context = getContext();

                    if (context != null) {
                        // E.g. a timeout's message is null
                        String reason = error.getMessage() != null ? error.getMessage() : error.getClass().getSimpleName();
                        MessageHelpers.showLongMessage(context, context.getString(R.string.release_notes_failed, reason));
                    }
                });
    }

    /**
     * What's new: the app's versions and the backend's deploys, fetched from the backend and shown as text
     */
    private void loadChangelogs() {
        if (RxHelper.isAnyActionRunning(sReleasesAction)) {
            return;
        }

        Context appContext = getContext().getApplicationContext();

        sReleasesAction = RxHelper.execute(Observable.fromCallable(() -> {
            UtubotClient client = UtubotManager.instance(appContext).newClient();
            List<Entry[]> both = new ArrayList<>();
            both.add(UtubotChangelog.parse(client.changelogJson(UtubotChangelog.KIND_APP)).toArray(new Entry[0]));
            both.add(UtubotChangelog.parse(client.changelogJson(UtubotChangelog.KIND_BACKEND)).toArray(new Entry[0]));

            return both;
        }), both -> showChangelogs(both.get(0), both.get(1)),
                error -> {
                    Context context = getContext();

                    if (context != null) {
                        String reason = error.getMessage() != null ? error.getMessage() : error.getClass().getSimpleName();
                        MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_whats_new_failed, reason));
                    }
                });
    }

    /**
     * Over the Updates panel (Back goes to it): the app's versions, then the backend's deploys, newest first; an entry opens its text
     */
    private void showChangelogs(Entry[] appEntries, Entry[] backendEntries) {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        // Closed while loading
        if (!dialogPresenter.isDialogShown()) {
            return;
        }

        if (appEntries.length == 0 && backendEntries.length == 0) {
            MessageHelpers.showMessage(getContext(), R.string.utubot_whats_new_none);
            return;
        }

        appendChangelogRows(dialogPresenter, getContext().getString(R.string.utubot_whats_new_app), appEntries);
        appendChangelogRows(dialogPresenter, getContext().getString(R.string.utubot_whats_new_backend), backendEntries);
        dialogPresenter.showDialog(getContext().getString(R.string.utubot_whats_new));
    }

    private void appendChangelogRows(AppDialogPresenter dialogPresenter, String label, Entry[] entries) {
        TimeZone zone = TimeZone.getDefault();

        for (Entry entry : entries) {
            String title = UtubotChangelog.title(label, entry, zone);
            dialogPresenter.appendSingleButton(UiOptionItem.from(title, option -> showChangelogText(title, entry)));
        }
    }

    private void showChangelogText(String title, Entry entry) {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());
        String text = UtubotChangelog.text(entry, TimeZone.getDefault(), getContext().getString(R.string.utubot_whats_new_no_changes));
        dialogPresenter.appendLongTextCategory(title, UiOptionItem.from(text), false);
        dialogPresenter.showDialog(title);
    }

    /**
     * The update channel of the u·tubot backend: its changelog is the release notes when GitHub can't be reached
     */
    @Nullable
    private String getChangelogFallbackUrl() {
        return UtubotSettings.isBuiltIn() ? UtubotSettings.instance(getContext()).getUpdateUrl() : null;
    }

    /**
     * Over the Updates panel: Back goes to it
     *
     * @param focused its row has the focus, e.g. the release whose notes were open: null for the first one
     */
    private void showReleases(List<Release> releases, @Nullable Release focused) {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        // Closed while loading
        if (!dialogPresenter.isDialogShown()) {
            return;
        }

        if (releases.isEmpty()) {
            MessageHelpers.showMessage(getContext(), R.string.release_notes_none);
            return;
        }

        String versionName = AppInfoHelpers.getAppVersionName(getContext());
        String tagPrefix = getContext().getString(R.string.release_notes_tag_prefix);

        for (Release release : releases) {
            OptionItem item = UiOptionItem.from(getTitle(release, versionName, tagPrefix), option -> showNotes(release, releases));
            dialogPresenter.appendSingleButton(item);

            if (release == focused) {
                dialogPresenter.setFocusedItem(item);
            }
        }

        dialogPresenter.showDialog(getContext().getString(R.string.release_notes));
    }

    /**
     * The installed version is marked and bold
     */
    private CharSequence getTitle(Release release, String versionName, String tagPrefix) {
        if (!GitHubReleases.isInstalled(release, versionName, tagPrefix)) {
            return release.version;
        }

        SpannableString title = new SpannableString(getContext().getString(R.string.release_notes_installed, release.version));
        title.setSpan(new StyleSpan(Typeface.BOLD), 0, title.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);

        return title;
    }

    private void showNotes(Release release, List<Release> releases) {
        // The notes are a web page: without a WebView, their text (the QR code of the release page is only for opening it on a phone)
        if (WebViewCompat.getCurrentWebViewPackage(getContext()) == null) {
            String text = Html.fromHtml(release.bodyHtml).toString().trim();
            AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());
            dialogPresenter.appendLongTextCategory(release.version, UiOptionItem.from(text), false);

            if (!TextUtils.isEmpty(release.pageUrl)) {
                dialogPresenter.appendSingleButton(UiOptionItem.from(getContext().getString(R.string.utubot_release_page_on_phone),
                        option -> QrCodePresenter.instance(getContext()).show(release.pageUrl)));
            }

            dialogPresenter.showDialog(release.version);
            return;
        }

        // Back to the list on this release, over the Updates panel
        ReleaseNotesPresenter.instance(getContext()).show(release, () -> showOverMenu(() -> showReleases(releases, release)));
    }

    private void showOverMenu(Runnable showList) {
        AppDialogPresenter presenter = AppDialogPresenter.instance(getContext());

        if (presenter.isDialogShown()) {
            showList.run();
            return;
        }

        // Before the menu is shown: a dialog that's still there shows it right away.
        // Posted: the menu is added to the stack first.
        presenter.setOnStart(() -> Utils.post(showList));
        presenter.enableNestedTitles(mIsNestedTitles);
        try {
            show(true);
        } finally {
            presenter.enableNestedTitles(false);
        }
    }
}
