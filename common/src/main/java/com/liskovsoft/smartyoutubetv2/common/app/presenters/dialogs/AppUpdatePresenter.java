package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs;

import android.annotation.SuppressLint;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.ErrorFragmentData;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utils.LoadingManager;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.ArrayList;
import java.util.List;

public class AppUpdatePresenter extends BasePresenter<Void> implements AppUpdateCheckerListener {
    @SuppressLint("StaticFieldLeak")
    private static AppUpdatePresenter sInstance;
    // Waits before the second and the third attempt of a forced check
    private static final long[] RETRY_DELAYS_MS = {10_000, 20_000};
    private final AppUpdateChecker mUpdateChecker;
    private final AppDialogPresenter mSettingsPresenter;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final Runnable mRetryCheck = this::forceCheck;
    private boolean mIsForceCheck;
    private boolean mIsForceCheckRunning;
    private int mFailedAttempts;

    public AppUpdatePresenter(Context context) {
        super(context);
        mUpdateChecker = new AppUpdateChecker(context, this);
        mSettingsPresenter = AppDialogPresenter.instance(context);
    }

    public static AppUpdatePresenter instance(Context context) {
        if (sInstance == null) {
            sInstance = new AppUpdatePresenter(context);
        }

        sInstance.setContext(context);

        return sInstance;
    }

    public static void unhold() {
        if (sInstance != null) {
            sInstance.stopForceCheck();
        }

        sInstance = null;
    }

    /**
     * After the app is finished: no retries and no messages
     */
    void stopForceCheck() {
        mIsForceCheck = false;
        mIsForceCheckRunning = false;
        mHandler.removeCallbacks(mRetryCheck);
    }

    /**
     * The built-in u-tubot flavor has no update source of its own: it follows the update_url of the imported setup, and
     * without one nothing is checked.
     */
    String[] getUpdateUrls() {
        if (UtubotSettings.isBuiltIn()) {
            String url = UtubotSettings.instance(getContext()).getUpdateUrl();

            return url.isEmpty() ? new String[0] : new String[]{url};
        }

        return getContext().getResources().getStringArray(R.array.update_urls);
    }

    public void start(boolean forceCheck) {
        // The running forced check reports back, after its retries
        if (mIsForceCheckRunning) {
            return;
        }

        mIsForceCheck = forceCheck;

        if (getUpdateUrls().length == 0) {
            if (forceCheck) {
                MessageHelpers.showMessage(getContext(), R.string.utubot_no_update_source);
            }

            onFinish();
            return;
        }

        if (forceCheck) {
            mIsForceCheckRunning = true;
            mFailedAttempts = 0;
            LoadingManager.showLoading(getContext(), true);
            forceCheck();
        } else {
            mUpdateChecker.checkForUpdates(getUpdateUrls());
        }
    }

    void forceCheck() {
        mUpdateChecker.forceCheckForUpdates(getUpdateUrls());
    }

    private void finishForceCheck() {
        mIsForceCheckRunning = false;
        mHandler.removeCallbacks(mRetryCheck);
        LoadingManager.showLoading(getContext(), false);
    }

    @Override
    public void onUpdateFound(String versionName, List<String> changelog, String apkPath) {
        if (mIsForceCheck) {
            finishForceCheck();
            showUpdateDialog(versionName, changelog, apkPath);
        } else if (UtubotSettings.isBuiltIn() || GeneralData.instance(getContext()).isOldUpdateNotificationsEnabled()) {
            showUpdateDialog(versionName, changelog, apkPath);
        } else {
            pinUpdateSection(versionName, changelog, apkPath);
        }
    }

    @Override
    public void onUpdateError(Exception error) {
        if (mIsForceCheck) {
            boolean isLatestVersion = AppUpdateCheckerListener.LATEST_VERSION.equals(error.getMessage());

            if (!isLatestVersion && mFailedAttempts < RETRY_DELAYS_MS.length) {
                // The spinner stays while waiting
                mHandler.postDelayed(mRetryCheck, RETRY_DELAYS_MS[mFailedAttempts++]);
                return;
            }

            finishForceCheck();

            if (isLatestVersion) {
                MessageHelpers.showMessage(getContext(), R.string.update_not_found);
            } else {
                MessageHelpers.showMessage(getContext(), String.format("%s: %s", getContext().getString(R.string.update_error),
                        getContext().getString(R.string.update_try_again_later)));
            }
        }

        onFinish();
    }

    private void showUpdateDialog(String versionName, List<String> changelog, String apkPath) {
        // Don't show update dialog if the player opened or the app is collapsed
        if (getContext() == null || getViewManager().isPlayerInForeground() || !Utils.isAppInForegroundFixed()) {
            return;
        }

        mSettingsPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.install_update), optionItem -> {
                    GeneralData.instance(getContext()).setChangelog(changelog);
                    mUpdateChecker.installUpdate();
                }, false));
        mSettingsPresenter.appendStringsCategory(getContext().getString(R.string.update_changelog), createChangelogOptions(changelog));
        //mSettingsPresenter.appendSingleSwitch(UiOptionItem.from(getContext().getString(R.string.show_again), optionItem -> {
        //    mUpdateChecker.enableUpdateCheck(optionItem.isSelected());
        //}, mUpdateChecker.isUpdateCheckEnabled()));

        //mSettingsPresenter.setOnFinish(getOnFinish());
        mSettingsPresenter.showDialog(String.format("%s %s", getContext().getString(R.string.app_name), versionName), AppUpdatePresenter::unhold);
    }

    private void pinUpdateSection(String versionName, List<String> changelog, String apkPath) {
        // Don't show update dialog if the player opened or the app is collapsed
        if (getContext() == null) {
            return;
        }

        BrowsePresenter.instance(getContext()).pinItem(getContext().getString(R.string.update_found), R.drawable.action_info, new ErrorFragmentData() {
            @Override
            public void onAction() {
                GeneralData.instance(getContext()).setChangelog(changelog);
                mUpdateChecker.installUpdate();
            }

            @Override
            public String getMessage() {
                return String.format("%s %s", getContext().getString(R.string.app_name), versionName) + " " +
                        getContext().getString(R.string.update_changelog) + ":\n" +
                        createChangelog(changelog);
            }

            @Override
            public String getActionText() {
                return getContext().getString(R.string.install_update);
            }
        });
    }

    private List<OptionItem> createChangelogOptions(List<String> changelog) {
        List<OptionItem> options = new ArrayList<>();

        for (String change : changelog) {
            options.add(UiOptionItem.from(change));
        }

        return options;
    }

    private String createChangelog(List<String> changelog) {
        StringBuilder builder = new StringBuilder();

        int maxLines = 30;
        int lineNum = 0;

        for (String change : changelog) {
            if (lineNum > maxLines) {
                break;
            }

            builder.append("- ");
            builder.append(change);
            builder.append("\n");

            lineNum++;
        }

        return builder.toString();
    }
}
