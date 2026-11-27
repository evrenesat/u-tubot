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
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCaptionStore.Usage;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utils.AppDialogUtil;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.function.IntSupplier;

import io.reactivex.Single;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * Settings → AI features: the AI feature switches and the prompt sets
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
        UtubotSettingsSyncRunner.requestNow(getContext());
        show(false);
    }

    /**
     * "Synced with host, 2 min ago", or that the server does not answer; null when the server has no web settings or the TV is not paired
     */
    private String syncStatusLine(Context context) {
        UtubotSettingsSync.Status status = UtubotSettingsSyncRunner.status();

        if (status == UtubotSettingsSync.Status.FAILED) {
            return context.getString(R.string.utubot_sync_failed);
        }

        long lastOk = UtubotSettingsSyncRunner.lastOkMs();

        if (status != UtubotSettingsSync.Status.SYNCED || lastOk == 0) {
            return null;
        }

        return context.getString(R.string.utubot_sync_ok, hostOf(mSettings.getUrl()), formatAgo(context, System.currentTimeMillis() - lastOk));
    }

    static String hostOf(String url) {
        try {
            String host = java.net.URI.create(url).getHost();
            return host != null ? host : url;
        } catch (IllegalArgumentException e) {
            return url;
        }
    }

    static String formatAgo(Context context, long ageMs) {
        long minutes = ageMs / TimeUnit.MINUTES.toMillis(1);

        if (minutes < 1) {
            return context.getString(R.string.utubot_sync_just_now);
        }

        return minutes < 60 ? context.getString(R.string.utubot_sync_minutes_ago, (int) minutes)
                : context.getString(R.string.utubot_sync_hours_ago, (int) (minutes / 60));
    }

    private void show(boolean replace) {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        dialog.enableReplace(replace);

        for (OptionCategory category : buildCategories()) {
            dialog.appendCategory(category);
        }

        dialog.showDialog(context.getString(R.string.utubot_ai_features));
    }

    /**
     * The AI features, always in this order: the switches, Summary delay, Auto captions, Auto cuts, Cut jump, Prompts, Caption storage
     */
    List<OptionCategory> buildCategories() {
        Context context = getContext();
        List<OptionCategory> categories = new ArrayList<>();
        String syncLine = syncStatusLine(context);

        if (syncLine != null) {
            categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_sync_title), syncLine,
                    option -> UtubotSettingsSyncRunner.requestNow(context))));
        }

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
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_auto_captions), context.getString(R.string.utubot_auto_captions_desc),
                option -> mSettings.setAutoCaptionsEnabled(option.isSelected()), mSettings.isAutoCaptionsEnabled())));
        categories.add(OptionCategory.singleSwitch(UiOptionItem.from(context.getString(R.string.utubot_auto_cuts), context.getString(R.string.utubot_auto_cuts_desc),
                option -> mSettings.setApplyReadyCutsEnabled(option.isSelected()), mSettings.isApplyReadyCutsEnabled())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_cut_jump),
                formatCutJump(context, mSettings.getCutJumpBinding()), option -> showCutJump())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_prompts), context.getString(R.string.utubot_prompts_desc),
                option -> showPrompts())));
        categories.add(OptionCategory.singleButton(UiOptionItem.from(context.getString(R.string.utubot_caption_storage),
                formatCaptionStorage(context, UtubotCaptionStore.instance(context).usage()), option -> showCaptionStorage())));

        return categories;
    }

    private void showCaptionStorage() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        appendDeleteAction(context, dialog, context.getString(R.string.utubot_caption_storage_delete_30),
                () -> UtubotCaptionStore.instance(context).deleteOlderThan(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(30)));
        appendDeleteAction(context, dialog, context.getString(R.string.utubot_caption_storage_delete_90),
                () -> UtubotCaptionStore.instance(context).deleteOlderThan(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(90)));
        appendDeleteAction(context, dialog, context.getString(R.string.utubot_caption_storage_delete_365),
                () -> UtubotCaptionStore.instance(context).deleteOlderThan(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(365)));
        appendDeleteAction(context, dialog, context.getString(R.string.utubot_caption_storage_delete_all),
                () -> UtubotCaptionStore.instance(context).deleteAll());

        dialog.showDialog(context.getString(R.string.utubot_caption_storage_delete));
    }

    private void appendDeleteAction(Context context, AppDialogPresenter dialog, String title, IntSupplier delete) {
        dialog.appendSingleButton(UiOptionItem.from(title, option -> AppDialogUtil.showConfirmationDialog(context,
                context.getString(R.string.utubot_caption_storage_confirm, title), () -> deleteCaptions(delete))));
    }

    private void deleteCaptions(IntSupplier delete) {
        RxHelper.disposeActions(mAction);
        mAction = Single.fromCallable(delete::getAsInt)
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(this::afterDelete, error -> {
                    MessageHelpers.showLongMessage(getContext(), getContext().getString(R.string.utubot_caption_storage_failed,
                            error.getMessage()));
                    show(true);
                });
    }

    private void afterDelete(int deleted) {
        Context context = getContext();

        if (deleted == 0) {
            MessageHelpers.showMessage(context, context.getString(R.string.utubot_caption_storage_none));
        } else {
            MessageHelpers.showMessage(context, context.getResources().getQuantityString(
                    R.plurals.utubot_caption_storage_deleted, deleted, deleted));
        }

        show(true);
    }

    /**
     * "12.4 MB · 3 videos · 5 tracks", with the warning under it when the store is large
     */
    static String formatCaptionStorage(Context context, Usage usage) {
        if (usage.tracks == 0) {
            return context.getString(R.string.utubot_caption_storage_empty);
        }

        String videos = context.getResources().getQuantityString(R.plurals.utubot_caption_storage_videos, usage.videos, usage.videos);
        String tracks = context.getResources().getQuantityString(R.plurals.utubot_caption_storage_tracks, usage.tracks, usage.tracks);
        String text = context.getString(R.string.utubot_caption_storage_usage, formatBytes(usage.bytes), videos, tracks);

        if (usage.bytes >= UtubotCaptionStore.WARN_BYTES) {
            text += "\n" + context.getString(R.string.utubot_caption_storage_warning, formatBytes(UtubotCaptionStore.WARN_BYTES));
        }

        return text;
    }

    static String formatBytes(long bytes) {
        if (bytes < 1024L * 1024L) {
            return String.format(Locale.ROOT, "%.1f KB", bytes / 1024.0);
        } else if (bytes < 1024L * 1024L * 1024L) {
            return String.format(Locale.ROOT, "%.1f MB", bytes / (1024.0 * 1024.0));
        }

        return String.format(Locale.ROOT, "%.1f GB", bytes / (1024.0 * 1024.0 * 1024.0));
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
        if (!UtubotSettings.isPanelDelayChoice(delayMs)) {
            return context.getString(R.string.utubot_panel_delay_custom, delayMs);
        }

        float seconds = delayMs / (float) MS_PER_SECOND;
        String text = seconds == Math.floor(seconds) ? String.valueOf((int) seconds) : String.valueOf(seconds);

        return context.getString(R.string.utubot_panel_delay_value, text);
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
}
