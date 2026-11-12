package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import java.util.Locale;
import java.util.concurrent.TimeUnit;

import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;

/**
 * The u-tubot items of the video context menu: the AI answer, the Summary panel switch and Prepare HQ captions
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

        boolean isPanelOn = settings.isSummaryPanelEnabled();
        dialog.appendSingleButton(UiOptionItem.from(context.getString(isPanelOn ? R.string.utubot_panel_on : R.string.utubot_panel_off),
                option -> settings.setSummaryPanelEnabled(!isPanelOn)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_prepare_captions), option -> prepareCaptions(context, video)));
    }

    private static void appendAnswer(Context context, AppDialogPresenter dialog, Video video) {
        Verdict verdict = UtubotManager.instance(context).getVerdict(video.videoId);
        String answer = UtubotPolicy.answerLabel(verdict);
        String title = answer != null ? context.getString(R.string.utubot_ai_answer_value, answer) : context.getString(R.string.utubot_ai_answer);
        dialog.appendSingleButton(UiOptionItem.from(title, option -> showAnswer(context, video)));
    }

    private static void showAnswer(Context context, Video video) {
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
    static String formatInsight(Context context, Insight insight) {
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
                .subscribe(status -> MessageHelpers.showMessage(context, context.getString(R.string.utubot_captions_status, status)),
                        error -> MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_captions_failed, error.getMessage())));
    }
}
