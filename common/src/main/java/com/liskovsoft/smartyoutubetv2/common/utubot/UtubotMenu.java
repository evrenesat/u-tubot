package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutMode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;

/**
 * The u-tubot items of the video context menu: the AI answer, the Summary panel switch, Prepare HQ captions and Director's cut
 */
public final class UtubotMenu {
    private static Disposable sAction;
    /** The mode picked in this picker session; null follows the cut list's default */
    @Nullable private static String sCutMode;
    /** The video the cut picker is currently showing, so a ready cut refreshes the open menu instead of starting the video over */
    @Nullable private static String sOpenVideoId;

    private UtubotMenu() {
    }

    /**
     * Appends the items at the top of the menu being built. Nothing without the u-tubot layer or its backend address.
     */
    public static void append(Context context, AppDialogPresenter dialog, @Nullable Video video) {
        UtubotSettings settings = UtubotSettings.instance(context);

        if (video == null || video.videoId == null || !settings.isConfigured()) {
            return;
        }

        if (settings.isAnswerInMenuEnabled()) {
            appendAnswer(context, dialog, video);
        }

        if (UtubotUiHost.canOpen()) {
            dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_summary_item),
                    option -> openInView(context, UtubotOpenRequests.Kind.SUMMARY, video)));
        }

        boolean isPanelOn = settings.isSummaryPanelEnabled();
        dialog.appendSingleButton(UiOptionItem.from(context.getString(isPanelOn ? R.string.utubot_panel_on : R.string.utubot_panel_off),
                option -> settings.setSummaryPanelEnabled(!isPanelOn)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_prepare_captions), option -> prepareCaptions(context, video, false)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_force_captions), option -> prepareCaptions(context, video, true)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_cut_menu), option -> showCuts(context, video)));
    }

    private static void appendAnswer(Context context, AppDialogPresenter dialog, Video video) {
        Verdict verdict = UtubotManager.instance(context).getVerdict(video.videoId);
        String answer = UtubotPolicy.answerLabel(verdict);
        String title = answer != null ? context.getString(R.string.utubot_ai_answer_value, answer) : context.getString(R.string.utubot_ai_answer);
        dialog.appendSingleButton(UiOptionItem.from(title, option -> showAnswer(context, video)));
    }

    /**
     * Closes the menu: the screen under it opens the Summary view or the answer when it resumes
     */
    private static void openInView(Context context, UtubotOpenRequests.Kind kind, Video video) {
        AppDialogPresenter.instance(context).closeDialog();
        UtubotUiHost.request(kind, video);
    }

    private static void showAnswer(Context context, Video video) {
        if (UtubotUiHost.canOpen()) {
            openInView(context, UtubotOpenRequests.Kind.ANSWER, video);
            return;
        }

        MessageHelpers.showMessage(context, context.getString(R.string.utubot_answer_loading));
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).insightObserve(video)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(insight -> showInsightDialog(context, video, insight),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_answer_failed, error.getMessage())));
    }

    private static void showInsightDialog(Context context, Video video, Insight insight) {
        if (insight.isFailed() || insight.isPending()) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_answer_failed,
                    insight.error != null ? insight.error : context.getString(R.string.utubot_answer_none)));
            return;
        }

        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        dialog.appendLongTextCategory(video.getTitle(), UiOptionItem.from(formatInsight(context, insight)));
        dialog.showDialog(video.getTitle());
    }

    /**
     * The answer first, then the summary, the key points, the share of the video that matters and the source
     */
    public static String formatInsight(Context context, Insight insight) {
        StringBuilder text = new StringBuilder();

        if (insight.titleQuestion != null) {
            text.append(insight.titleQuestion).append("\n");
        }

        appendParagraph(text, insight.answer);
        appendParagraph(text, insight.summary);

        if (!insight.keyPoints.isEmpty()) {
            text.append("\n").append(context.getString(R.string.utubot_answer_key_points)).append("\n");

            for (String point : insight.keyPoints) {
                text.append("- ").append(point).append("\n");
            }
        }

        if (insight.inflation != null && insight.inflation.durationSec > 0) {
            text.append("\n").append(context.getString(R.string.utubot_answer_inflation,
                    formatClock(insight.inflation.essentialSec), formatClock(insight.inflation.durationSec))).append("\n");
        }

        if (insight.source != null) {
            text.append("\n").append(context.getString(R.string.utubot_answer_source, insight.source));
        }

        return text.toString().trim();
    }

    private static void appendParagraph(StringBuilder text, @Nullable String paragraph) {
        if (paragraph != null && !paragraph.isEmpty()) {
            text.append("\n").append(paragraph).append("\n");
        }
    }

    static String formatClock(long seconds) {
        long hours = TimeUnit.SECONDS.toHours(seconds);
        long minutes = TimeUnit.SECONDS.toMinutes(seconds) % TimeUnit.HOURS.toMinutes(1);
        long rest = seconds % TimeUnit.MINUTES.toSeconds(1);

        return hours > 0 ? String.format(Locale.ROOT, "%d:%02d:%02d", hours, minutes, rest) : String.format(Locale.ROOT, "%d:%02d", minutes, rest);
    }

    private static void prepareCaptions(Context context, Video video, boolean force) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).prepareCaptionsObserve(video.videoId, force)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(status -> {
                            MessageHelpers.showMessage(context, context.getString(R.string.utubot_captions_status, status));
                            UtubotManager.instance(context).captionsRequested(video.videoId, status);
                        },
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_captions_failed, error.getMessage())));
    }

    //region Director's cut

    /**
     * Opens the cut picker for a video: its presets and their state, the actions, the phone sheet. The video menu and the player
     * button both come here.
     */
    public static void showCuts(Context context, Video video) {
        sCutMode = null;
        rebuildCuts(context, video);
    }

    /**
     * Re-fetches the cuts and rebuilds the picker. Resetting the session's mode is the caller's call: {@link #showCuts} starts fresh,
     * {@link #refresh} keeps it, so a building row can re-render as ready without losing the mode the owner picked.
     */
    static void rebuildCuts(Context context, Video video) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).cutsObserve(video.videoId, UtubotMeta.from(video))
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(update -> {
                    if (update.render) {
                        showCutsDialog(context, video, update.cuts, false, update.stale);
                    }
                }, error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_cut_failed, error.getMessage())));
    }

    /**
     * Rebuilds the picker of a video whose cut became ready while it was open (issue 197), keeping the session's mode. The app-wide
     * notice calls it when a building cut is ready and its menu is still up, so the row stops saying "Building…" and shows the ready state.
     */
    public static void refresh(Context context, String videoId) {
        rebuildCuts(context, Video.from(videoId));
    }

    /**
     * The cut picker is open for this video, so a ready cut refreshes it instead of starting the video over
     */
    public static boolean isCutsMenuOpen(@Nullable String videoId) {
        return videoId != null && videoId.equals(sOpenVideoId);
    }

    private static void showCutsDialog(Context context, Video video, CutList cuts, boolean force) {
        showCutsDialog(context, video, cuts, force, false);
    }

    private static void showCutsDialog(Context context, Video video, CutList cuts, boolean force, boolean stale) {
        if (!cuts.configured) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_cut_not_configured));
            return;
        }

        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        dialog.closeDialog();
        sOpenVideoId = video.videoId; // set after the close: the row below re-renders as soon as this cut becomes ready
        UtubotCutController controller = PlaybackPresenter.instance(context).getController(UtubotCutController.class);

        // A refresh just failed: the cache is shown under a notice, so the viewer knows it is not the latest
        if (stale) {
            List<OptionItem> hint = new ArrayList<>();
            hint.add(UiOptionItem.from(context.getString(R.string.utubot_cut_stale_hint)));
            dialog.appendCategory(OptionCategory.stringList(context.getString(R.string.utubot_cut_stale), hint));
        }

        String mode = selectedMode(cuts);
        CutMode modeInfo = cuts.mode(mode);

        dialog.appendSingleButton(UiOptionItem.from(modeTitle(context, cuts, mode),
                option -> pickTheOtherMode(context, video, cuts, force)));

        for (CutPreset preset : cuts.presets) {
            CutPreset shown = preset.forMode(mode);

            dialog.appendSingleButton(UiOptionItem.from(presetTitle(context, shown), stateText(context, shown, controller),
                    option -> onPresetPicked(context, video, shown, controller, mode, cuts, force)));

            // A ready cut shows its kept parts under the preset, so the owner can judge it on the
            // TV before applying it (checkpoint 4; the phone sheet already does this). Each part
            // jumps the playing video to its start when pressed, keeping the cut active.
            if (shown.isReady() && !shown.cut.parts.isEmpty()) {
                dialog.appendCategory(partsCategory(context, shown.cut, controller));
            }

            // A failed Watched preset offers the same preset in Quick with one press.
            if (CutMode.WATCHED.equals(mode) && UtubotModels.CutState.FAILED.equals(shown.state)) {
                dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_cut_use_quick),
                        option -> startPresetRequest(context, video, shown.id, CutMode.QUICK, cuts, force)));
            }
        }

        appendChannelDefault(context, dialog, video, cuts);
        dialog.appendSingleButton(UiOptionItem.from(context.getString(
                force ? R.string.utubot_cut_force_on : R.string.utubot_cut_force_off),
                option -> showCutsDialog(context, video, cuts, !force)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_cut_describe_on_phone),
                option -> describeOnPhone(context, video, mode)));
        dialog.setOnFinish(() -> sOpenVideoId = null);
        dialog.showDialog(context.getString(R.string.utubot_cut));
    }

    /**
     * "Always use quick cuts for this channel" for the mode on screen (so a talking-head channel is set once, and the mode
     * stays switchable per video), and "Follow your default" while that mode is already the channel's own. The channel's
     * mode wins over the user's choice and the server default (request > channel > user > server).
     */
    private static void appendChannelDefault(Context context, AppDialogPresenter dialog, Video video, CutList cuts) {
        String channelId = cuts.channelId != null ? cuts.channelId : video.channelId;

        if (channelId == null) {
            return;
        }

        String channelName = cuts.channelName != null ? cuts.channelName : video.getAuthor();
        String mode = selectedMode(cuts);
        boolean follows = mode.equals(cuts.channelMode);
        String label = follows
                ? context.getString(R.string.utubot_cut_channel_follow)
                : context.getString(R.string.utubot_cut_channel_always, modeLabel(context, mode));

        dialog.appendSingleButton(UiOptionItem.from(label, option -> saveChannelDefault(context, channelId, channelName,
                follows ? null : mode)));
    }

    private static void saveChannelDefault(Context context, String channelId, @Nullable String channelName, @Nullable String mode) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).channelCutModeObserve(channelId, mode, channelName)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(saved -> MessageHelpers.showMessage(context, context.getString(R.string.utubot_cut_channel_saved)),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_cut_failed,
                                describeError(context, error))));
    }

    private static String modeLabel(Context context, String mode) {
        return context.getString(UtubotModels.CutMode.WATCHED.equals(mode)
                ? R.string.utubot_cut_mode_watched : R.string.utubot_cut_mode_quick);
    }

    private static String selectedMode(CutList cuts) {
        if (sCutMode != null) {
            return sCutMode;
        }
        return cuts.defaultMode != null ? cuts.defaultMode : CutMode.QUICK;
    }

    /**
     * "Mode: Quick (default)" / "Mode: Watched · about N min": the first row of the picker
     */
    private static String modeTitle(Context context, CutList cuts, String mode) {
        CutMode info = cuts.mode(mode);
        if (info == null) {
            return context.getString(R.string.utubot_cut_mode, mode);
        }
        StringBuilder text = new StringBuilder(info.label != null ? info.label : info.id);
        if (info.defaultMode || mode.equals(cuts.defaultMode)) {
            text.append(" ").append(context.getString(R.string.utubot_cut_mode_default));
        }
        if (!info.available && info.reason != null) {
            text.append(" (").append(info.reason).append(")");
        }
        return context.getString(R.string.utubot_cut_mode, text.toString());
    }

    /**
     * The other mode; an unavailable one says its reason instead of switching
     */
    private static void pickTheOtherMode(Context context, Video video, CutList cuts, boolean force) {
        String other = CutMode.WATCHED.equals(selectedMode(cuts)) ? CutMode.QUICK : CutMode.WATCHED;
        CutMode info = cuts.mode(other);
        if (info == null) {
            return;
        }
        if (!info.available) {
            MessageHelpers.showLongMessage(context, info.reason != null ? info.reason : context.getString(R.string.utubot_answer_none));
            return;
        }
        sCutMode = other;
        AppDialogPresenter.instance(context).closeDialog();
        showCutsDialog(context, video, cuts, force);
    }

    private static String presetTitle(Context context, CutPreset preset) {
        if (!preset.isReady()) {
            return preset.label;
        }
        String title = UtubotCutController.presetTitle(preset.label, preset.cut.keptMs);
        return CutMode.WATCHED.equals(preset.cut.mode)
                ? title + context.getString(R.string.utubot_cut_watched_suffix)
                : title;
    }

    /**
     * The state of the preset's cut for this video, under its label
     */
    private static String stateText(Context context, CutPreset preset, @Nullable UtubotCutController controller) {
        if (preset.isReady()) {
            String length = context.getString(R.string.utubot_cut_state_ready_length,
                    UtubotCutController.formatLength(preset.cut.keptMs),
                    UtubotCutController.formatLength(preset.cut.durationMs));

            return controller != null && controller.isApplied(preset.cut)
                    ? context.getString(R.string.utubot_cut_state_ready_on, length)
                    : length;
        }

        switch (preset.state) {
            case UtubotModels.CutState.WAITING:
                return context.getString(R.string.utubot_cut_state_waiting);
            case UtubotModels.CutState.BUILDING:
                return context.getString(R.string.utubot_cut_state_building);
            case UtubotModels.CutState.NEEDS_TRANSCRIPT:
                // The server says what happens next (it waits for this TV's captions after YouTube refused it)
                return preset.error != null && !preset.error.isEmpty()
                        ? preset.error
                        : context.getString(R.string.utubot_cut_state_needs_transcript);
            case UtubotModels.CutState.FAILED:
                return preset.error != null
                        ? context.getString(R.string.utubot_cut_state_failed, preset.error)
                        : context.getString(R.string.utubot_cut_state_failed_plain);
            default:
                return context.getString(R.string.utubot_cut_state_none);
        }
    }

    /**
     * The kept parts of a ready cut, as a list: each part's times and label, with the
     * one-line summary above them. A part is pressed to jump the playing video to its start and
     * keep the cut active (the picker closes first).
     */
    private static OptionCategory partsCategory(Context context, Cut cut, @Nullable UtubotCutController controller) {
        List<OptionItem> parts = new ArrayList<>();

        if (cut.summary != null && !cut.summary.trim().isEmpty()) {
            parts.add(UiOptionItem.from(cut.summary.trim()));
        }

        for (CutPart part : cut.parts) {
            final CutPart partForCallback = part;
            parts.add(UiOptionItem.from(UtubotCutController.formatPart(part), option -> {
                AppDialogPresenter.instance(context).closeDialog();
                if (controller != null) {
                    controller.jumpToPart(cut, partForCallback);
                }
            }));
        }

        return OptionCategory.stringList(context.getString(R.string.utubot_cut_parts, cut.label), parts);
    }

    private static void onPresetPicked(Context context, Video video, CutPreset preset, @Nullable UtubotCutController controller,
                                       String mode, CutList cuts, boolean force) {
        if (!force && UtubotModels.CutState.READY.equals(preset.state) && preset.cut != null) {
            AppDialogPresenter.instance(context).closeDialog(); // the state text is stale the moment the cut is toggled or the video opens

            if (controller != null && controller.toggle(preset.cut)) {
                return; // the video that plays: applied or turned off in place
            }

            // Opened from a list: the cut is carried into the normal playback path, applied as that video opens
            if (controller != null) {
                controller.applyOnOpen(preset.cut);
            }

            PlaybackPresenter.instance(context).openVideo(video);
            return;
        }

        if (!force && !preset.canRequest()) {
            return; // waiting or building without force: the state is the information; nothing to do
        }

        startPresetRequest(context, video, preset.id, mode, cuts, force);
    }

    /**
     * Asks for one preset in a mode (Quick or Watched); Watched says its estimate before the video keeps playing.
     */
    private static void startPresetRequest(Context context, Video video, String presetId, String mode, CutList cuts,
                                           boolean force) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).requestCutObserve(video.videoId, presetId, null, false, UtubotMeta.from(video), mode, force)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(request -> {
                    if (CutMode.WATCHED.equals(mode)) {
                        long eta = cuts.mode(CutMode.WATCHED) != null ? cuts.mode(CutMode.WATCHED).etaSec : UtubotModels.UNKNOWN;
                        MessageHelpers.showMessage(context, eta > 0
                                ? context.getString(R.string.utubot_cut_watched_started, formatClock(eta))
                                : context.getString(R.string.utubot_cut_watched_started_plain));
                    } else {
                        MessageHelpers.showMessage(context, context.getString(R.string.utubot_cut_state_building));
                    }
                    UtubotManager.instance(context).cutRequested(video.videoId, request.id, request.state);

                    if (UtubotCutWatcher.isPending(request.state)) {
                        UtubotCutNotices.instance(context).ordered(request.id, video.videoId, video.getTitle());
                    }
                }, error -> MessageHelpers.showLongMessage(context,
                        context.getString(R.string.utubot_cut_failed, describeError(context, error))));
    }

    /**
     * "Describe on phone…": a waiting request for the phone, its address as a QR code. The video keeps playing.
     */
    private static void describeOnPhone(Context context, Video video, String mode) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).requestCutObserve(video.videoId, null, null, true, UtubotMeta.from(video), mode)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(request -> {
                    showPhoneSheet(context, request);
                    UtubotManager.instance(context).cutRequested(video.videoId, request.id, request.state);

                    if (UtubotCutWatcher.isPending(request.state)) {
                        UtubotCutNotices.instance(context).ordered(request.id, video.videoId, video.getTitle());
                    }
                }, error -> MessageHelpers.showLongMessage(context,
                        context.getString(R.string.utubot_cut_describe_failed, describeError(context, error))));
    }

    /**
     * The waiting request as a QR code and its short address, over the playing video
     */
    private static void showPhoneSheet(Context context, CutRequest request) {
        AppDialogPresenter.instance(context).closeDialog();
        UtubotCutQrView.show(context, UtubotManager.instance(context).cutRequestUrl(request.id),
                context.getString(R.string.utubot_cut_describe_hint));
    }

    private static String describeError(Context context, Throwable error) {
        return error.getMessage() != null ? error.getMessage() : context.getString(R.string.utubot_answer_none);
    }

    //endregion
}
