package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import java.util.Locale;
import java.util.concurrent.TimeUnit;

import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;

/**
 * The u-tubot items of the video context menu: the AI answer, the Summary panel switch, Prepare HQ captions and Director's cut
 */
public final class UtubotMenu {
    private static Disposable sAction;

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
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_prepare_captions), option -> prepareCaptions(context, video)));
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

    private static void prepareCaptions(Context context, Video video) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).prepareCaptionsObserve(video.videoId)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(status -> {
                            MessageHelpers.showMessage(context, context.getString(R.string.utubot_captions_status, status));
                            UtubotManager.instance(context).captionsRequested(video.videoId, status);
                        },
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_captions_failed, error.getMessage())));
    }

    //region Director's cut

    private static void showCuts(Context context, Video video) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).cutsObserve(video.videoId)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(cuts -> showCutsDialog(context, video, cuts),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_cut_failed, error.getMessage())));
    }

    private static void showCutsDialog(Context context, Video video, CutList cuts) {
        if (!cuts.configured) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_cut_not_configured));
            return;
        }

        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        dialog.closeDialog();
        UtubotCutController controller = PlaybackPresenter.instance(context).getController(UtubotCutController.class);

        for (CutPreset preset : cuts.presets) {
            dialog.appendSingleButton(UiOptionItem.from(preset.label, stateText(context, preset, controller),
                    option -> onPresetPicked(context, video, preset, controller)));
        }

        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_cut_describe_on_phone),
                option -> describeOnPhone(context, video)));
        dialog.showDialog(context.getString(R.string.utubot_cut));
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
                return context.getString(R.string.utubot_cut_state_needs_transcript);
            case UtubotModels.CutState.FAILED:
                return preset.error != null
                        ? context.getString(R.string.utubot_cut_state_failed, preset.error)
                        : context.getString(R.string.utubot_cut_state_failed_plain);
            default:
                return context.getString(R.string.utubot_cut_state_none);
        }
    }

    private static void onPresetPicked(Context context, Video video, CutPreset preset, @Nullable UtubotCutController controller) {
        if (UtubotModels.CutState.READY.equals(preset.state) && preset.cut != null) {
            if (controller != null) {
                AppDialogPresenter.instance(context).closeDialog(); // the state text is stale the moment the cut is toggled
                controller.toggle(preset.cut);
            }

            return;
        }

        if (!UtubotModels.CutState.NONE.equals(preset.state)) {
            return; // the state is the information; nothing to do
        }

        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).requestCutObserve(video.videoId, preset.id, null, false, UtubotMeta.from(video))
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(request -> {
                    MessageHelpers.showMessage(context, context.getString(R.string.utubot_cut_state_building));
                    UtubotManager.instance(context).cutRequested(video.videoId, request.id, request.state);
                }, error -> MessageHelpers.showLongMessage(context,
                        context.getString(R.string.utubot_cut_failed, describeError(context, error))));
    }

    /**
     * "Describe on phone…": a waiting request for the phone, its address as a QR code. The video keeps playing.
     */
    private static void describeOnPhone(Context context, Video video) {
        RxHelper.disposeActions(sAction);
        sAction = UtubotManager.instance(context).requestCutObserve(video.videoId, null, null, true, UtubotMeta.from(video))
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(request -> {
                    showPhoneSheet(context, request);
                    UtubotManager.instance(context).cutRequested(video.videoId, request.id, request.state);
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
