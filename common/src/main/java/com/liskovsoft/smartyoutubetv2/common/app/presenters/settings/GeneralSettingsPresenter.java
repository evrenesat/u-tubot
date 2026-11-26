package com.liskovsoft.smartyoutubetv2.common.app.presenters.settings;

import android.annotation.SuppressLint;
import android.content.Context;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.okhttp.OkHttpManager;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerConstants;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.misc.MediaServiceManager;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.prefs.NetworkData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;
import com.liskovsoft.smartyoutubetv2.common.prefs.SearchData;
import com.liskovsoft.smartyoutubetv2.common.proxy.ProxyManager;
import com.liskovsoft.smartyoutubetv2.common.proxy.WebProxyDialog;
import com.liskovsoft.smartyoutubetv2.common.utils.AppDialogUtil;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.smartyoutubetv2.common.utubot.BrowseCachePolicy;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.youtubeapi.service.internal.MediaServiceData;

import java.util.ArrayList;
import java.util.List;

public class GeneralSettingsPresenter extends BasePresenter<Void> {
    private final GeneralData mGeneralData;
    private final PlayerData mPlayerData;
    private final PlayerTweaksData mPlayerTweaksData;
    private final MainUIData mMainUIData;
    private final MediaServiceData mMediaServiceData;
    private final NetworkData mNetworkData;
    private boolean mRestartApp;
    private final Runnable mOnFinish = () -> {
        if (mRestartApp) {
            mRestartApp = false;
            MessageHelpers.showLongMessage(getContext(), R.string.msg_restart_app);
        }
    };

    private GeneralSettingsPresenter(Context context) {
        super(context);
        mGeneralData = GeneralData.instance(context);
        mPlayerData = PlayerData.instance(context);
        mPlayerTweaksData = PlayerTweaksData.instance(context);
        mMainUIData = MainUIData.instance(context);
        mMediaServiceData = MediaServiceData.instance();
        mNetworkData = NetworkData.instance(context);
    }

    public static GeneralSettingsPresenter instance(Context context) {
        return new GeneralSettingsPresenter(context);
    }

    /**
     * The Background playback card of the System settings, in General (was in the General panel)
     */
    public void showBackgroundPlayback() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendBackgroundPlaybackCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.category_background_playback), mOnFinish);
    }

    /**
     * The Browse refresh card of the System settings, in General (was in the u·tubot panel)
     */
    public void showBrowseRefresh() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendBrowseRefreshCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.utubot_browse_refresh), mOnFinish);
    }

    /**
     * The Screen dimming card of the System settings, in General (was in the General panel)
     */
    public void showScreenDimming() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendScreenDimmingAmountCategory(settingsPresenter);
        appendScreenDimmingTimeoutCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.screen_dimming), mOnFinish);
    }

    /**
     * The Key remapping card of the System settings, in General (was in the General panel)
     */
    public void showKeyRemapping() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendKeyRemappingCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.key_remapping), mOnFinish);
    }

    /**
     * The Network settings card of the System settings, in General (was in the General panel)
     */
    public void showNetwork() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendInternetCensorship(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.network_settings), mOnFinish);
    }

    /**
     * The History card of the System settings, in General (was in the General panel)
     */
    public void showHistory() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendHistoryCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.header_history), mOnFinish);
    }

    /**
     * The API keys card of the System settings, in General (was in the General panel)
     */
    public void showApiKeys() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendDataApiKeySwitch(settingsPresenter);
        appendDataApiKeyButton(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.api_keys), mOnFinish);
    }

    /**
     * The DNS card of the System settings (was Prefers in the Player settings)
     */
    public void showDns() {
        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from(getContext().getString(R.string.prefer_ipv4),
                getContext().getString(R.string.prefer_ipv4_desc),
                option -> {
                    // OkHttp is the only engine that supports custom DNS
                    mPlayerTweaksData.setPlayerDataSource(option.isSelected() ? PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP : Utils.getFasterDataSource());
                    mPlayerTweaksData.setPreferredDnsType(option.isSelected() ? PlayerTweaksData.DNS_TYPE_IPV4 : PlayerTweaksData.DNS_TYPE_SYSTEM);
                    mRestartApp = true;
                },
                mPlayerTweaksData.getPreferredDnsType() == PlayerTweaksData.DNS_TYPE_IPV4));

        options.add(UiOptionItem.from(getContext().getString(R.string.prefer_google_dns),
                getContext().getString(R.string.prefer_ipv4_desc),
                option -> {
                    // OkHttp is the only engine that supports custom DNS
                    mPlayerTweaksData.setPlayerDataSource(option.isSelected() ? PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP : Utils.getFasterDataSource());
                    mPlayerTweaksData.setPreferredDnsType(option.isSelected() ? PlayerTweaksData.DNS_TYPE_GOOGLE : PlayerTweaksData.DNS_TYPE_SYSTEM);
                    mRestartApp = true;
                },
                mPlayerTweaksData.getPreferredDnsType() == PlayerTweaksData.DNS_TYPE_GOOGLE));

        showOptions(R.string.settings_dns, options);
    }

    /**
     * The Misc options card of the System settings, in General (was Misc in the General panel)
     */
    public void showMisc() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendMiscCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.settings_misc_options), mOnFinish);
    }

    /**
     * The Child mode card of the System settings, in General (was in Misc options)
     */
    public void showChildMode() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendChildModeCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.child_mode), mOnFinish);
    }

    /**
     * The Remember options card of the System settings, in General (was in the General panel)
     */
    public void showRemember() {
        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from(getContext().getString(R.string.remember_position_subscriptions),
                option -> mGeneralData.setRememberSubscriptionsPositionEnabled(option.isSelected()),
                mGeneralData.isRememberSubscriptionsPositionEnabled()));

        options.add(UiOptionItem.from(getContext().getString(R.string.remember_position_pinned),
                option -> mGeneralData.setRememberPinnedPositionEnabled(option.isSelected()),
                mGeneralData.isRememberPinnedPositionEnabled()));

        showOptions(R.string.settings_remember_options, options);
    }

    /**
     * The Disable options card of the System settings, in General (was in the General panel)
     */
    public void showDisable() {
        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from(getContext().getString(R.string.disable_screensaver),
                option -> mGeneralData.setScreensaverDisabled(option.isSelected()),
                mGeneralData.isScreensaverDisabled()));

        // Disable long press on buggy controllers.
        options.add(UiOptionItem.from(getContext().getString(R.string.disable_ok_long_press),
                getContext().getString(R.string.disable_ok_long_press_desc),
                option -> mGeneralData.setOkButtonLongPressDisabled(option.isSelected()),
                mGeneralData.isOkButtonLongPressDisabled()));

        showOptions(R.string.settings_disable_options, options);
    }

    private void showOptions(int titleResId, List<OptionItem> options) {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        String title = getContext().getString(titleResId);
        settingsPresenter.appendCheckedCategory(title, options);
        settingsPresenter.showDialog(title, mOnFinish);
    }

    /**
     * The Password options card of the System settings, in General (was in the General panel)
     */
    public void showPasswords() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from(getContext().getString(R.string.protect_settings_with_password),
                option -> {
                    if (option.isSelected()) {
                        showPasswordDialog(settingsPresenter, null);
                    } else {
                        mGeneralData.setSettingsPassword(null);
                    }
                },
                mGeneralData.getSettingsPassword() != null));

        options.add(UiOptionItem.from(getContext().getString(R.string.enable_master_password),
                option -> {
                    if (option.isSelected()) {
                        showMasterPasswordDialog(settingsPresenter, null);
                    } else {
                        mGeneralData.setMasterPassword(null);
                    }
                },
                mGeneralData.getMasterPassword() != null));

        String title = getContext().getString(R.string.settings_password_options);
        settingsPresenter.appendCheckedCategory(title, options);
        settingsPresenter.showDialog(title, mOnFinish);
    }

    /**
     * The Exit from options card of the System settings, in General (was in the General panel): one list, the app exit opens from it
     */
    public void showExit() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        List<OptionItem> options = new ArrayList<>();

        OptionItem appExit = UiOptionItem.from(getContext().getString(R.string.app_exit_shortcut), option -> showAppExitMenu());
        appExit.setMenu(true);
        options.add(appExit);

        options.add(UiOptionItem.from( getContext().getString(R.string.player_exit_shortcut) + ": " + getContext().getString(R.string.app_double_back_exit),
                option -> mGeneralData.setPlayerExitShortcut(option.isSelected() ? GeneralData.EXIT_DOUBLE_BACK : GeneralData.EXIT_SINGLE_BACK),
                mGeneralData.getPlayerExitShortcut() == GeneralData.EXIT_DOUBLE_BACK));

        options.add(UiOptionItem.from(getContext().getString(R.string.search_exit_shortcut) + ": " + getContext().getString(R.string.app_double_back_exit),
                option -> mGeneralData.setSearchExitShortcut(option.isSelected() ? GeneralData.EXIT_DOUBLE_BACK : GeneralData.EXIT_SINGLE_BACK),
                mGeneralData.getSearchExitShortcut() == GeneralData.EXIT_DOUBLE_BACK));

        String title = getContext().getString(R.string.settings_exit_options);
        settingsPresenter.appendCheckedCategory(title, options);
        settingsPresenter.showDialog(title, mOnFinish);
    }

    private void showAppExitMenu() {
        AppDialogPresenter settingsPresenter = AppDialogPresenter.instance(getContext());

        appendAppExitCategory(settingsPresenter);

        settingsPresenter.showDialog(getContext().getString(R.string.app_exit_shortcut));
    }

    private void appendAppExitCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        for (int[] pair : new int[][] {
                {R.string.app_exit_none, GeneralData.EXIT_NONE},
                {R.string.app_double_back_exit, GeneralData.EXIT_DOUBLE_BACK},
                {R.string.app_single_back_exit, GeneralData.EXIT_SINGLE_BACK}}) {
            options.add(UiOptionItem.from(getContext().getString(pair[0]),
                    optionItem -> mGeneralData.setAppExitShortcut(pair[1]),
                    mGeneralData.getAppExitShortcut() == pair[1]));
        }

        settingsPresenter.appendRadioCategory(getContext().getString(R.string.app_exit_shortcut), options);
    }

    private void appendBackgroundPlaybackCategory(AppDialogPresenter settingsPresenter) {
        OptionCategory category = AppDialogUtil.createBackgroundPlaybackCategory(getContext(), mPlayerData, mGeneralData);
        settingsPresenter.appendRadioCategory(category.title, category.options);
    }

    private void appendBrowseRefreshCategory(AppDialogPresenter settingsPresenter) {
        UtubotSettings settings = UtubotSettings.instance(getContext());
        List<OptionItem> options = new ArrayList<>();

        for (int minutes : BrowseCachePolicy.REFRESH_MINUTES_CHOICES) {
            options.add(UiOptionItem.from(UtubotSettings.formatBrowseRefresh(getContext(), minutes),
                    option -> settings.setBrowseRefreshMinutes(minutes),
                    minutes == settings.getBrowseRefreshMinutes()));
        }

        settingsPresenter.appendRadioCategory(getContext().getString(R.string.utubot_browse_refresh), options);
    }

    private void appendKeyRemappingCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from("OK -> " + getContext().getString(R.string.player_toggle_speed),
                option -> mPlayerData.setOKButtonBehavior(option.isSelected() ? PlayerData.OK_TOGGLE_SPEED : PlayerData.OK_ONLY_UI),
                mPlayerData.getOKButtonBehavior() == PlayerData.OK_TOGGLE_SPEED));

        options.add(UiOptionItem.from(getContext().getString(R.string.player_quick_shorts_skip_alt),
                option -> {
                    mPlayerTweaksData.setQuickSkipShortsAltEnabled(option.isSelected());
                    mGeneralData.setDpadUpDownAction(GeneralData.ACTION_UNDEFINED);
                },
                mPlayerTweaksData.isQuickSkipShortsAltEnabled()));

        options.add(UiOptionItem.from(getContext().getString(R.string.player_quick_shorts_skip),
                option -> {
                    mPlayerTweaksData.setQuickSkipShortsEnabled(option.isSelected());
                    mGeneralData.resetDpadLeftRightSettings();
                },
                mPlayerTweaksData.isQuickSkipShortsEnabled()));

        options.add(UiOptionItem.from(getContext().getString(R.string.player_quick_skip_videos_alt),
                option -> {
                    mPlayerTweaksData.setQuickSkipVideosAltEnabled(option.isSelected());
                    mGeneralData.setDpadUpDownAction(GeneralData.ACTION_UNDEFINED);
                },
                mPlayerTweaksData.isQuickSkipVideosAltEnabled()));
        
        options.add(UiOptionItem.from(getContext().getString(R.string.player_quick_skip_videos),
                option -> {
                    mPlayerTweaksData.setQuickSkipVideosEnabled(option.isSelected());
                    mGeneralData.resetDpadLeftRightSettings();
                },
                mPlayerTweaksData.isQuickSkipVideosEnabled()));

        options.add(UiOptionItem.from("Play/Pause -> OK",
                option -> mGeneralData.setRemapPlayToOKEnabled(option.isSelected()),
                mGeneralData.isRemapPlayToOKEnabled()));

        options.add(UiOptionItem.from("DPAD RIGHT/LEFT -> Volume Up/Down",
                option -> {
                    mGeneralData.setRemapDpadLeftToVolumeEnabled(option.isSelected());
                    mPlayerTweaksData.resetDpadLeftRightSettings();
                },
                mGeneralData.isRemapDpadLeftToVolumeEnabled()));

        options.add(UiOptionItem.from("DPAD UP/DOWN -> Volume Up/Down",
                option -> {
                    mGeneralData.setDpadUpDownAction(option.isSelected() ? GeneralData.ACTION_VOLUME_UP_DOWN : GeneralData.ACTION_UNDEFINED);
                    mPlayerTweaksData.resetDpadUpDownSettings();
                },
                mGeneralData.getDpadUpDownAction() == GeneralData.ACTION_VOLUME_UP_DOWN));

        options.add(UiOptionItem.from("DPAD UP/DOWN -> Speed Up/Down",
                option -> {
                    mGeneralData.setDpadUpDownAction(option.isSelected() ? GeneralData.ACTION_SPEED_UP_DOWN : GeneralData.ACTION_UNDEFINED);
                    mPlayerTweaksData.resetDpadUpDownSettings();
                },
                mGeneralData.getDpadUpDownAction() == GeneralData.ACTION_SPEED_UP_DOWN));

        options.add(UiOptionItem.from("Numbers 3/1 -> Speed Up/Down",
                option -> mGeneralData.setRemapNumbersToSpeedEnabled(option.isSelected()),
                mGeneralData.isRemapNumbersToSpeedEnabled()));

        options.add(UiOptionItem.from("Next/Previous -> Fast Forward/Rewind",
                option -> mGeneralData.setNextPreviousAction(option.isSelected() ? GeneralData.ACTION_FAST_FORWARD_REWIND : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getNextPreviousAction() == GeneralData.ACTION_FAST_FORWARD_REWIND));

        options.add(UiOptionItem.from("Next/Previous -> Speed Up/Down",
                option -> mGeneralData.setNextPreviousAction(option.isSelected() ? GeneralData.ACTION_SPEED_UP_DOWN : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getNextPreviousAction() == GeneralData.ACTION_SPEED_UP_DOWN));

        options.add(UiOptionItem.from("Fast Forward/Rewind -> Next/Previous",
                option -> mGeneralData.setFastForwardRewindAction(option.isSelected() ? GeneralData.ACTION_NEXT_PREVIOUS : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getFastForwardRewindAction() == GeneralData.ACTION_NEXT_PREVIOUS));

        options.add(UiOptionItem.from("Fast Forward/Rewind -> Speed Up/Down",
                option -> mGeneralData.setFastForwardRewindAction(option.isSelected() ? GeneralData.ACTION_SPEED_UP_DOWN : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getFastForwardRewindAction() == GeneralData.ACTION_SPEED_UP_DOWN));

        options.add(UiOptionItem.from("Fast Forward/Rewind -> Speed Toggle",
                option -> mGeneralData.setFastForwardRewindAction(option.isSelected() ? GeneralData.ACTION_SPEED_TOGGLE : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getFastForwardRewindAction() == GeneralData.ACTION_SPEED_TOGGLE));

        options.add(UiOptionItem.from("S -> Speed Toggle",
                option -> mGeneralData.setRemapSToSpeedToggleEnabled(option.isSelected()),
                mGeneralData.isRemapSToSpeedToggleEnabled()));

        options.add(UiOptionItem.from("Page Up/Down -> Next/Previous",
                option -> mGeneralData.setPageUpDownAction(option.isSelected() ? GeneralData.ACTION_NEXT_PREVIOUS : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getPageUpDownAction() == GeneralData.ACTION_NEXT_PREVIOUS));

        options.add(UiOptionItem.from("Page Up/Down -> Like/Dislike",
                option -> mGeneralData.setPageUpDownAction(option.isSelected() ? GeneralData.ACTION_LIKE_DISLIKE : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getPageUpDownAction() == GeneralData.ACTION_LIKE_DISLIKE));

        options.add(UiOptionItem.from("Page Up/Down -> Speed Up/Down",
                option -> mGeneralData.setPageUpDownAction(option.isSelected() ? GeneralData.ACTION_SPEED_UP_DOWN : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getPageUpDownAction() == GeneralData.ACTION_SPEED_UP_DOWN));
        
        options.add(UiOptionItem.from("Page Up/Down -> Speed Down/Up",
                option -> mGeneralData.setPageUpDownAction(option.isSelected() ? GeneralData.ACTION_SPEED_DOWN_UP : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getPageUpDownAction() == GeneralData.ACTION_SPEED_DOWN_UP));

        options.add(UiOptionItem.from("Channel Up/Down -> Volume Up/Down",
                option -> mGeneralData.setChannelUpDownAction(option.isSelected() ? GeneralData.ACTION_VOLUME_UP_DOWN : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getChannelUpDownAction() == GeneralData.ACTION_VOLUME_UP_DOWN));

        options.add(UiOptionItem.from("Channel Up/Down -> Next/Previous",
                option -> mGeneralData.setChannelUpDownAction(option.isSelected() ? GeneralData.ACTION_NEXT_PREVIOUS : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getChannelUpDownAction() == GeneralData.ACTION_NEXT_PREVIOUS));

        options.add(UiOptionItem.from("Channel Up/Down -> Like/Dislike",
                option -> mGeneralData.setChannelUpDownAction(option.isSelected() ? GeneralData.ACTION_LIKE_DISLIKE : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getChannelUpDownAction() == GeneralData.ACTION_LIKE_DISLIKE));

        options.add(UiOptionItem.from("Channel Up/Down -> Speed Up/Down",
                option -> mGeneralData.setChannelUpDownAction(option.isSelected() ? GeneralData.ACTION_SPEED_UP_DOWN : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getChannelUpDownAction() == GeneralData.ACTION_SPEED_UP_DOWN));

        options.add(UiOptionItem.from("Channel Up/Down -> Speed Toggle",
                option -> mGeneralData.setChannelUpDownAction(option.isSelected() ? GeneralData.ACTION_SPEED_TOGGLE : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getChannelUpDownAction() == GeneralData.ACTION_SPEED_TOGGLE));

        options.add(UiOptionItem.from("Channel Up/Down -> Search",
                option -> mGeneralData.setChannelUpDownAction(option.isSelected() ? GeneralData.ACTION_SEARCH : GeneralData.ACTION_UNDEFINED),
                mGeneralData.getChannelUpDownAction() == GeneralData.ACTION_SEARCH));

        settingsPresenter.appendCheckedCategory(getContext().getString(R.string.key_remapping), options);
    }

    private void appendScreenDimmingAmountCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        int activeMode = mGeneralData.getScreensaverDimmingPercents();

        for (int dimPercents : Helpers.range(10, 80, 10)) {
            options.add(UiOptionItem.from(
                    dimPercents + "%",
                    option -> mGeneralData.setScreensaverDimmingPercents(dimPercents),
                    activeMode == dimPercents));
        }

        for (int dimPercents : Helpers.range(85, 100, 5)) {
            options.add(UiOptionItem.from(
                    dimPercents + "%",
                    option -> mGeneralData.setScreensaverDimmingPercents(dimPercents),
                    activeMode == dimPercents));
        }

        settingsPresenter.appendRadioCategory(getContext().getString(R.string.screen_dimming_amount), options);
    }

    @SuppressLint("StringFormatMatches")
    private void appendScreenDimmingTimeoutCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        int screensaverTimeoutMs = mGeneralData.getScreensaverTimeoutMs();

        options.add(UiOptionItem.from(
                getContext().getString(R.string.option_never),
                option -> mGeneralData.setScreensaverTimeoutMs(GeneralData.SCREENSAVER_TIMEOUT_NEVER),
                screensaverTimeoutMs == GeneralData.SCREENSAVER_TIMEOUT_NEVER));

        for (int timeoutSec : new int[] {5, 15, 30}) {
            int timeoutMs = timeoutSec * 1_000;
            options.add(UiOptionItem.from(
                    getContext().getString(R.string.ui_hide_timeout_sec, timeoutSec),
                    option -> mGeneralData.setScreensaverTimeoutMs(timeoutMs),
                    screensaverTimeoutMs == timeoutMs));
        }

        for (int i = 1; i <= 15; i++) {
            int timeoutMs = i * 60 * 1_000;
            options.add(UiOptionItem.from(
                    getContext().getString(R.string.screen_dimming_timeout_min, i),
                    option -> mGeneralData.setScreensaverTimeoutMs(timeoutMs),
                    screensaverTimeoutMs == timeoutMs));
        }

        settingsPresenter.appendRadioCategory(getContext().getString(R.string.screen_dimming_timeout), options);
    }

    //private void appendTimeFormatCategory(AppDialogPresenter settingsPresenter) {
    //    List<OptionItem> options = new ArrayList<>();
    //
    //    options.add(UiOptionItem.from(
    //            getContext().getString(R.string.time_format_24),
    //            option -> {
    //                mGeneralData.setTimeFormat(GeneralData.TIME_FORMAT_24);
    //                mRestartApp = true;
    //            },
    //            mGeneralData.getTimeFormat() == GeneralData.TIME_FORMAT_24));
    //
    //    options.add(UiOptionItem.from(
    //            getContext().getString(R.string.time_format_12),
    //            option -> {
    //                mGeneralData.setTimeFormat(GeneralData.TIME_FORMAT_12);
    //                mRestartApp = true;
    //            },
    //            mGeneralData.getTimeFormat() == GeneralData.TIME_FORMAT_12));
    //
    //    settingsPresenter.appendRadioCategory(getContext().getString(R.string.time_format), options);
    //}

    private void appendHistoryCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        for (int[] pair : new int[][] {
                {R.string.auto_history, GeneralData.HISTORY_AUTO},
                {R.string.enable_history, GeneralData.HISTORY_ENABLED},
                {R.string.disable_history_local, GeneralData.HISTORY_DISABLED},
                {R.string.disable_history_global, GeneralData.HISTORY_PAUSED}}) {
            options.add(UiOptionItem.from(getContext().getString(pair[0]),
                    optionItem -> MediaServiceManager.instance().applyHistoryState(getContext(), pair[1]),
                    mGeneralData.getHistoryState() == pair[1]));
        }

        settingsPresenter.appendRadioCategory(getContext().getString(R.string.header_history), options);
    }

    private void appendChildModeCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from(getContext().getString(R.string.child_mode),
                getContext().getString(R.string.child_mode_desc),
                option -> {
                    if (option.isSelected()) {
                        AppDialogUtil.showConfirmationDialog(getContext(), getContext().getString(R.string.lost_setting_warning),
                                () -> showPasswordDialog(settingsPresenter, () -> enableChildMode(option.isSelected())),
                                settingsPresenter::closeDialog);
                    } else {
                        mGeneralData.setSettingsPassword(null);
                        enableChildMode(option.isSelected());
                        settingsPresenter.closeDialog();
                    }
                },
                mGeneralData.isChildModeEnabled()));

        settingsPresenter.appendCheckedCategory(getContext().getString(R.string.child_mode), options);
    }

    private void appendMiscCategory(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        options.add(UiOptionItem.from(getContext().getString(R.string.return_to_launcher),
                option -> mGeneralData.setReturnToLauncherEnabled(option.isSelected()),
                mGeneralData.isReturnToLauncherEnabled()));

        options.add(UiOptionItem.from(getContext().getString(R.string.select_channel_section),
                option -> mGeneralData.setSelectChannelSectionEnabled(option.isSelected()),
                mGeneralData.isSelectChannelSectionEnabled()));

        settingsPresenter.appendCheckedCategory(getContext().getString(R.string.settings_misc_options), options);
    }

    private void appendDataApiKeySwitch(AppDialogPresenter settingsPresenter) {
        settingsPresenter.appendSingleSwitch(UiOptionItem.from(getContext().getString(R.string.data_api_key),
                option -> {
                    if (option.isSelected()) {
                        showDataApiKeyDialog(settingsPresenter);
                    } else {
                        mMediaServiceData.setDataApiKey(null);
                    }
                },
                mMediaServiceData.getDataApiKey() != null));
    }

    /**
     * Opens the key in the editor: the switch can only enter a new key or remove the current one
     */
    private void appendDataApiKeyButton(AppDialogPresenter settingsPresenter) {
        settingsPresenter.appendSingleButton(UiOptionItem.from(getContext().getString(R.string.data_api_key_change),
                option -> showDataApiKeyDialog(settingsPresenter)));
    }

    private void appendInternetCensorship(AppDialogPresenter settingsPresenter) {
        List<OptionItem> options = new ArrayList<>();

        appendProxyManager(settingsPresenter, options);

        appendConscrypt(settingsPresenter, options);

        appendIpv6Test(options);

        settingsPresenter.appendCheckedCategory(getContext().getString(R.string.network_settings), options);
    }

    private void appendProxyManager(AppDialogPresenter settingsPresenter, List<OptionItem> options) {
        ProxyManager proxyManager = new ProxyManager(getContext());

        if (proxyManager.isProxySupported()) {
            options.add(UiOptionItem.from(getContext().getString(R.string.enable_web_proxy),
                    option -> {
                        // Proxy with authentication supported only by OkHttp
                        mPlayerTweaksData.setPlayerDataSource(
                                option.isSelected() ? PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP : PlayerTweaksData.PLAYER_DATA_SOURCE_CRONET);
                        mGeneralData.setProxyEnabled(option.isSelected());
                        new WebProxyDialog(getContext()).enable(option.isSelected());
                        if (option.isSelected()) {
                            settingsPresenter.closeDialog();
                        }

                        OkHttpManager.unhold();
                    },
                    mGeneralData.isProxyEnabled()));
        }
    }

    private void appendConscrypt(AppDialogPresenter settingsPresenter, List<OptionItem> options) {
        options.add(UiOptionItem.from(getContext().getString(R.string.enable_conscrypt),
                getContext().getString(R.string.enable_conscrypt_desc),
                option -> {
                    mNetworkData.setConscryptEnabled(option.isSelected());
                    mRestartApp = true;
                },
                mNetworkData.isConscryptEnabled()));
    }

    private void appendIpv6Test(List<OptionItem> options) {
        options.add(UiOptionItem.from(getContext().getString(R.string.ipv6_test),
                getContext().getString(R.string.ipv6_test_desc),
                // Applies at the next connection, no restart (see Ipv6CheckDns)
                option -> mPlayerTweaksData.setIpv6TestEnabled(option.isSelected()),
                mPlayerTweaksData.isIpv6TestEnabled()));
    }

    private void enableChildMode(boolean enable) {
        mGeneralData.setChildModeEnabled(enable);

        int playerButtons = PlayerTweaksData.PLAYER_BUTTON_PLAY_PAUSE | PlayerTweaksData.PLAYER_BUTTON_NEXT | PlayerTweaksData.PLAYER_BUTTON_PREVIOUS |
                    PlayerTweaksData.PLAYER_BUTTON_DISLIKE | PlayerTweaksData.PLAYER_BUTTON_LIKE | PlayerTweaksData.PLAYER_BUTTON_SCREEN_DIMMING |
                    PlayerTweaksData.PLAYER_BUTTON_SEEK_INTERVAL | PlayerTweaksData.PLAYER_BUTTON_PLAYBACK_QUEUE | PlayerTweaksData.PLAYER_BUTTON_OPEN_CHANNEL |
                    PlayerTweaksData.PLAYER_BUTTON_PIP | PlayerTweaksData.PLAYER_BUTTON_VIDEO_SPEED | PlayerTweaksData.PLAYER_BUTTON_SUBTITLES |
                    PlayerTweaksData.PLAYER_BUTTON_VIDEO_ZOOM | PlayerTweaksData.PLAYER_BUTTON_ADD_TO_PLAYLIST;
        long menuItems = MainUIData.MENU_ITEM_SHOW_QUEUE | MainUIData.MENU_ITEM_ADD_TO_QUEUE | MainUIData.MENU_ITEM_PLAY_NEXT |
                    MainUIData.MENU_ITEM_STREAM_REMINDER | MainUIData.MENU_ITEM_SAVE_REMOVE_PLAYLIST;

        PlayerTweaksData tweaksData = PlayerTweaksData.instance(getContext());
        SearchData searchData = SearchData.instance(getContext());

        // Remove all
        mMainUIData.setTopButtonDisabled(Integer.MAX_VALUE);
        tweaksData.setPlayerButtonDisabled(Integer.MAX_VALUE);
        mMainUIData.setAllMenuItemsDisabled();
        BrowsePresenter.instance(getContext()).enableAllSections(false);
        searchData.setPopularSearchesDisabled(true);

        if (enable) {
            // apply child tweaks. No top buttons: no search and no other account (see NavigateTitleView)
            tweaksData.setPlayerButtonEnabled(playerButtons);
            mMainUIData.setMenuItemsEnabled(menuItems);
            mPlayerData.setPlaybackMode(PlayerConstants.PLAYBACK_MODE_LIST);
            BrowsePresenter.instance(getContext()).enableSection(MediaGroup.TYPE_HISTORY, true);
            BrowsePresenter.instance(getContext()).enableSection(MediaGroup.TYPE_USER_PLAYLISTS, true);
            BrowsePresenter.instance(getContext()).enableSection(MediaGroup.TYPE_SUBSCRIPTIONS, true);
            BrowsePresenter.instance(getContext()).enableSection(MediaGroup.TYPE_CHANNEL_UPLOADS, true);
        } else {
            // apply default tweaks
            mMainUIData.setTopButtonEnabled(MainUIData.TOP_BUTTON_DEFAULT);
            tweaksData.setPlayerButtonEnabled(PlayerTweaksData.PLAYER_BUTTON_DEFAULT);
            mMainUIData.setDefaultMenuItemsEnabled();
            BrowsePresenter.instance(getContext()).enableAllSections(true);
            // Each one is enabled again at its default index in a shorter list (see SidebarService.enableSection), so they're out of order
            BrowsePresenter.instance(getContext()).sortSectionsByDefault();
            tweaksData.setSuggestionsDisabled(false);
            mPlayerData.setPlaybackMode(PlayerConstants.PLAYBACK_MODE_ALL);
            searchData.setPopularSearchesDisabled(false);
        }
    }

    private void showPasswordDialog(AppDialogPresenter settingsPresenter, Runnable onSuccess) {
        if (mGeneralData.getSettingsPassword() != null) {
            if (onSuccess != null) {
                onSuccess.run();
            }
            return;
        }

        settingsPresenter.closeDialog();
        SimpleEditDialog.showPassword(
                getContext(),
                getContext().getString(R.string.protect_settings_with_password),
                null,
                newValue -> {
                    mGeneralData.setSettingsPassword(newValue);
                    if (onSuccess != null) {
                        onSuccess.run();
                    }
                    return true;
                });
    }

    private void showDataApiKeyDialog(AppDialogPresenter settingsPresenter) {
        settingsPresenter.closeDialog();
        SimpleEditDialog.show(
                getContext(),
                getContext().getString(R.string.data_api_key),
                getContext().getString(R.string.data_api_key_hint),
                mMediaServiceData.getDataApiKey(),
                newValue -> {
                    mMediaServiceData.setDataApiKey(newValue);
                    checkDataApiKey(mMediaServiceData.getDataApiKey());
                    return true;
                });
    }

    private void checkDataApiKey(String key) {
        if (key == null) {
            return;
        }

        Context context = getContext();

        RxHelper.execute(getMediaItemService().checkDataApiKeyObserve(key),
                reason -> MessageHelpers.showLongMessage(context, reason.isEmpty() ?
                        context.getString(R.string.data_api_key_works) : context.getString(R.string.data_api_key_fails, reason)),
                error -> MessageHelpers.showLongMessage(context, context.getString(R.string.data_api_key_fails, error.getMessage())));
    }

    private void showMasterPasswordDialog(AppDialogPresenter settingsPresenter, Runnable onSuccess) {
        if (mGeneralData.getMasterPassword() != null) {
            if (onSuccess != null) {
                onSuccess.run();
            }
            return;
        }

        settingsPresenter.closeDialog();
        SimpleEditDialog.showPassword(
                getContext(),
                getContext().getString(R.string.enable_master_password),
                null,
                newValue -> {
                    mGeneralData.setMasterPassword(newValue);
                    if (onSuccess != null) {
                        onSuccess.run();
                    }
                    return true;
                });
    }
}
