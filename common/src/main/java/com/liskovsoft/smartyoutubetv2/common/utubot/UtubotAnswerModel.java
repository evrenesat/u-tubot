package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

import java.util.Collections;
import java.util.function.Function;

import io.reactivex.Observable;
import io.reactivex.Scheduler;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;

/**
 * The AI answer of a video (the insight call) as the state the Summary view draws, so it gets the same indicator, scrolling and
 * Retry. Only the latest request counts.
 */
public class UtubotAnswerModel {
    private static final int SECONDS_PER_MINUTE = 60;

    public interface Source {
        Observable<Insight> insightObserve(Video video);
    }

    private final Source mSource;
    private final Function<Insight, String> mFormat;
    private final UtubotPanelModel.Listener mListener;
    private final Scheduler mUiScheduler;
    private final RequestGeneration mGeneration = new RequestGeneration();
    private Video mVideo;
    private Disposable mAction;

    public UtubotAnswerModel(Source source, Function<Insight, String> format, UtubotPanelModel.Listener listener) {
        this(source, format, listener, AndroidSchedulers.mainThread());
    }

    public UtubotAnswerModel(Source source, Function<Insight, String> format, UtubotPanelModel.Listener listener, Scheduler uiScheduler) {
        mSource = source;
        mFormat = format;
        mListener = listener;
        mUiScheduler = uiScheduler;
    }

    public void show(Video video) {
        if (video == null || video.videoId == null) {
            return;
        }

        mVideo = video;
        load();
    }

    @Nullable
    public Video getVideo() {
        return mVideo;
    }

    public void retry() {
        if (mVideo != null) {
            load();
        }
    }

    public void dispose() {
        mGeneration.invalidate();

        if (mAction != null) {
            mAction.dispose();
            mAction = null;
        }

        mVideo = null;
    }

    private void load() {
        long token = mGeneration.begin();

        if (mAction != null) {
            mAction.dispose();
        }

        publish(Phase.LOADING, null, null, null);
        mAction = mSource.insightObserve(mVideo)
                .observeOn(mUiScheduler)
                .subscribe(insight -> {
                    if (mGeneration.isCurrent(token)) {
                        onInsight(insight);
                    }
                }, error -> {
                    if (mGeneration.isCurrent(token)) {
                        publish(Phase.FAILED, null, null, error.getMessage());
                    }
                });
    }

    /**
     * Like a summary, an insight can say that the transcript is the reason there is no answer (see "Transcript status" of
     * ai/CONTRACT.md). The answer view only shows it: Retry asks again, and the way to a transcription is the Summary view's.
     */
    private void onInsight(Insight insight) {
        if (insight.isFailed()) {
            publishState(Phase.FAILED, null, insight.source, insight.error, null, insight);
        } else if (insight.needsTranscript()) {
            publishState(Phase.NEEDS_TRANSCRIPT, null, insight.source, null, insight.message, insight);
        } else if (insight.isDelayed()) {
            publishState(Phase.DELAYED, null, insight.source, null, insight.message != null ? insight.message : insight.error, insight);
        } else if (insight.isTranscribing()) {
            publishState(Phase.TRANSCRIBING, null, insight.source, null, null, insight);
        } else if (insight.isPending()) {
            publish(Phase.PENDING, null, insight.source, null);
        } else {
            publish(Phase.READY, mFormat.apply(insight), insight.source, null);
        }
    }

    private void publishState(Phase phase, @Nullable String text, @Nullable String source, @Nullable String error, @Nullable String message,
                              Insight insight) {
        int estimateMinutes = insight.estimateSec == UtubotModels.UNKNOWN ? 0 : Math.max(1, (insight.estimateSec + SECONDS_PER_MINUTE - 1) / SECONDS_PER_MINUTE);
        mListener.onState(new State(mVideo, phase, Collections.emptyList(), null, null, text, source, error, message, insight.canTranscribe, estimateMinutes,
                insight.progressPercent, insight.reason));
    }

    private void publish(Phase phase, @Nullable String text, @Nullable String source, @Nullable String error) {
        mListener.onState(new State(mVideo, phase, Collections.emptyList(), null, null, text, source, error));
    }
}
