package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;

import java.util.ArrayList;
import java.util.List;

import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Settings → u-tubot: the backend, the switches, the connection test and the prompt sets
 */
public class UtubotSettingsPresenter extends BasePresenter<Void> {
    private static final int MS_PER_SECOND = 1000;
    private final UtubotSettings mSettings;
    private final UtubotManager mManager;
    private Disposable mAction;

    private UtubotSettingsPresenter(Context context) {
        super(context);
        mSettings = UtubotSettings.instance(context);
        mManager = UtubotManager.instance(context);
    }

    public static UtubotSettingsPresenter instance(Context context) {
        return new UtubotSettingsPresenter(context);
    }

    public void show() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        for (OptionCategory category : buildCategories()) {
            dialog.appendCategory(category);
        }

        dialog.showDialog(context.getString(R.string.utubot_title));
    }

    /**
     * The main page, always in this order: Import setup, Pair with code, the switches (Summary panel and its delay), Prompts, Test connection, Advanced
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
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_assess), context.getString(R.string.utubot_assess_desc),
                option -> mSettings.setAssessEnabled(option.isSelected()), mSettings.isAssessEnabled())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_mark_only), context.getString(R.string.utubot_mark_only_desc),
                option -> mSettings.setMarkOnly(option.isSelected()), mSettings.isMarkOnly())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_answer_in_menu), context.getString(R.string.utubot_answer_in_menu_desc),
                option -> mSettings.setAnswerInMenuEnabled(option.isSelected()), mSettings.isAnswerInMenuEnabled())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_summary_panel), context.getString(R.string.utubot_summary_panel_desc),
                option -> mSettings.setSummaryPanelEnabled(option.isSelected()), mSettings.isSummaryPanelEnabled())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_panel_delay),
                formatDelay(context, mSettings.getPanelDelayMs()), option -> showPanelDelays())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_auto_scroll),
                formatAutoScroll(context, mSettings.getAutoScrollSpeedPxPerSec()), option -> showAutoScrollSpeeds())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_browse_refresh),
                formatBrowseRefresh(context, mSettings.getBrowseRefreshMinutes()), option -> showBrowseRefresh())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_update_interval),
                formatBrowseRefresh(context, mSettings.getUpdateIntervalMinutes()), option -> showUpdateInterval())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_development_mode), context.getString(R.string.utubot_development_mode_desc),
                option -> mSettings.setDevelopmentMode(option.isSelected()), mSettings.isDevelopmentMode())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_auto_captions), context.getString(R.string.utubot_auto_captions_desc),
                option -> mSettings.setAutoCaptionsEnabled(option.isSelected()), mSettings.isAutoCaptionsEnabled())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_auto_cuts), context.getString(R.string.utubot_auto_cuts_desc),
                option -> mSettings.setApplyReadyCutsEnabled(option.isSelected()), mSettings.isApplyReadyCutsEnabled())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_cut_jump),
                formatCutJump(context, mSettings.getCutJumpBinding()), option -> showCutJump())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_prompts), option -> showPrompts())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_test_connection), option -> testConnection())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_advanced), context.getString(R.string.utubot_advanced_desc),
                option -> showAdvanced())));

        return categories;
    }

    private void showPanelDelays() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        List<OptionItem> options = new ArrayList<>();

        for (int delayMs : UtubotSettings.PANEL_DELAY_CHOICES_MS) {
            options.add(UiOptionItem.from(formatDelay(context, delayMs), option -> mSettings.setPanelDelayMs(delayMs),
                    delayMs == mSettings.getPanelDelayMs()));
        }

        dialog.appendRadioCategory(context.getString(R.string.utubot_panel_delay), options);
        dialog.showDialog(context.getString(R.string.utubot_panel_delay));
    }

    private void showCutJump() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        List<OptionItem> options = new ArrayList<>();

        for (int binding : UtubotSettings.CUT_JUMP_CHOICES) {
            options.add(UiOptionItem.from(formatCutJump(context, binding), option -> mSettings.setCutJumpBinding(binding),
                    binding == mSettings.getCutJumpBinding()));
        }

        dialog.appendRadioCategory(context.getString(R.string.utubot_cut_jump), options);
        dialog.showDialog(context.getString(R.string.utubot_cut_jump));
    }

    /**
     * "Double-press Left / Right", "Double-press Up / Down", "Off"
     */
    static String formatCutJump(Context context, int binding) {
        if (binding == UtubotSettings.CUT_JUMP_UP_DOWN) {
            return context.getString(R.string.utubot_cut_jump_value_up_down);
        }

        if (binding == UtubotSettings.CUT_JUMP_OFF) {
            return context.getString(R.string.utubot_cut_jump_value_off);
        }

        return context.getString(R.string.utubot_cut_jump_value_left_right);
    }

    private void showBrowseRefresh() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        List<OptionItem> options = new ArrayList<>();

        for (int minutes : BrowseCachePolicy.REFRESH_MINUTES_CHOICES) {
            options.add(UiOptionItem.from(formatBrowseRefresh(context, minutes), option -> mSettings.setBrowseRefreshMinutes(minutes),
                    minutes == mSettings.getBrowseRefreshMinutes()));
        }

        dialog.appendRadioCategory(context.getString(R.string.utubot_browse_refresh), options);
        dialog.showDialog(context.getString(R.string.utubot_browse_refresh));
    }

    private void showUpdateInterval() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        List<OptionItem> options = new ArrayList<>();

        for (int minutes : UtubotSettings.UPDATE_INTERVAL_CHOICES_MINUTES) {
            options.add(UiOptionItem.from(formatBrowseRefresh(context, minutes), option -> mSettings.setUpdateIntervalMinutes(minutes),
                    minutes == mSettings.getUpdateIntervalMinutes()));
        }

        dialog.appendRadioCategory(context.getString(R.string.utubot_update_interval), options);
        dialog.showDialog(context.getString(R.string.utubot_update_interval));
    }

    /**
     * The reading pace of the self-scrolling summary/answer text: one of {@link UtubotSettings#AUTO_SCROLL_SPEEDS_PX_PER_SEC}
     */
    private void showAutoScrollSpeeds() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        List<OptionItem> options = new ArrayList<>();

        for (int pxPerSec : UtubotSettings.AUTO_SCROLL_SPEEDS_PX_PER_SEC) {
            options.add(UiOptionItem.from(formatAutoScroll(context, pxPerSec), option -> mSettings.setAutoScrollSpeedPxPerSec(pxPerSec),
                    pxPerSec == mSettings.getAutoScrollSpeedPxPerSec()));
        }

        dialog.appendRadioCategory(context.getString(R.string.utubot_auto_scroll), options);
        dialog.showDialog(context.getString(R.string.utubot_auto_scroll));
    }

    /**
     * "30 px/s", "45 px/s"
     */
    static String formatAutoScroll(Context context, int pxPerSec) {
        return context.getString(R.string.utubot_auto_scroll_value, String.valueOf(pxPerSec));
    }

    /**
     * "1 s", "1.8 s"
     */
    static String formatDelay(Context context, int delayMs) {
        float seconds = delayMs / (float) MS_PER_SECOND;
        String text = seconds == Math.floor(seconds) ? String.valueOf((int) seconds) : String.valueOf(seconds);

        return context.getString(R.string.utubot_panel_delay_value, text);
    }

    /**
     * "10 min"
     */
    static String formatBrowseRefresh(Context context, int minutes) {
        return context.getString(R.string.utubot_browse_refresh_value, String.valueOf(minutes));
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

    private void testConnection() {
        mAction = UtubotConnectionTest.run(getContext(), mAction);
    }

    private void showPrompts() {
        Context context = getContext();

        if (!mSettings.isConfigured()) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_not_configured));
            return;
        }

        MessageHelpers.showMessage(context, context.getString(R.string.utubot_prompts_loading));
        RxHelper.disposeActions(mAction);
        mAction = mManager.promptsObserve(true)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(this::showPromptsDialog,
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_prompts_failed, error.getMessage())));
    }

    private void showPromptsDialog(PromptList list) {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        List<OptionItem> options = new ArrayList<>();

        for (PromptSet set : list.sets) {
            for (Prompt prompt : set.prompts) {
                options.add(UiOptionItem.from(context.getString(R.string.utubot_prompts_set_line, prompt.label, set.name),
                        option -> setDefault(prompt), prompt.key.equals(list.defaultKey)));
            }
        }

        dialog.appendRadioCategory(context.getString(R.string.utubot_prompts_default), options);
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_prompts_import), option -> enterImportUrl()));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_prompts_refresh), option -> refreshAll()));
        dialog.showDialog(context.getString(R.string.utubot_prompts));
    }

    private void setDefault(Prompt prompt) {
        Context context = getContext();
        RxHelper.disposeActions(mAction);
        mAction = mManager.setDefaultPromptObserve(prompt.key)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(done -> {
                            mManager.setSessionPrompt(null);
                            MessageHelpers.showMessage(context, context.getString(R.string.utubot_prompts_default_set, prompt.label));
                        },
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_prompts_failed, error.getMessage())));
    }

    private void enterImportUrl() {
        Context context = getContext();
        AppDialogPresenter.instance(context).closeDialog();
        SimpleEditDialog.showUrl(context, context.getString(R.string.utubot_prompts_import), context.getString(R.string.utubot_prompts_import_hint),
                "", newValue -> {
                    importFrom(newValue.trim());
                    return true;
                });
    }

    private void importFrom(String url) {
        Context context = getContext();

        if (url.isEmpty()) {
            return;
        }

        RxHelper.disposeActions(mAction);
        mAction = mManager.importPromptsObserve(url)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(done -> MessageHelpers.showMessage(context, context.getString(R.string.utubot_prompts_imported, url)),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_prompts_import_failed, error.getMessage())));
    }

    private void refreshAll() {
        Context context = getContext();
        RxHelper.disposeActions(mAction);
        mAction = mManager.refreshPromptsObserve()
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(done -> MessageHelpers.showMessage(context, context.getString(R.string.utubot_prompts_refreshed)),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_prompts_failed, error.getMessage())));
    }

    private static String emptyToDash(String text) {
        return text.isEmpty() ? "-" : text;
    }
}
