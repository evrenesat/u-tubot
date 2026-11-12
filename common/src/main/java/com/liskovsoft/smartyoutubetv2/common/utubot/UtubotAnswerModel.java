package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

import java.util.Collections;
import java.util.function.Function;

import io.reactivex.Observable;
import io.reactivex.Scheduler;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.CompositeDisposable;

/**
 * The AI answer of a video (the insight call) as the state the Summary view draws, so it gets the same indicator, scrolling and
 * Retry. Only the latest request counts.
 * <p>
 * It waits like the Summary view does while the transcript is the reason there is no answer: a delayed request is asked again after the
 * time the backend gives (with the seconds counting down), and a transcription that is running (started by the backend's own policy)
 * is followed until it is done, then the answer is asked for again. Both end with {@link #dispose()}.
 */
public class UtubotAnswerModel {
    public interface Source {
        Observable<Insight> insightObserve(Video video);

        /** Where the transcript of a video stands */
        Observable<Transcript> transcriptObserve(String videoId);
    }

    private final Source mSource;
    private final Function<Insight, String> mFormat;
    private final UtubotPanelModel.Listener mListener;
    private final Scheduler mUiScheduler;
    private final UtubotScheduler mTimer;
    private final UtubotCountdown mRetryCountdown;
    private final Runnable mPollTask = this::pollTranscript;
    private final RequestGeneration mGeneration = new RequestGeneration();
    private final CompositeDisposable mActions = new CompositeDisposable();
    private Video mVideo;
    private State mState;

    public UtubotAnswerModel(Source source, Function<Insight, String> format, UtubotPanelModel.Listener listener) {
        this(source, format, listener, AndroidSchedulers.mainThread());
    }

    public UtubotAnswerModel(Source source, Function<Insight, String> format, UtubotPanelModel.Listener listener, Scheduler uiScheduler) {
        this(source, format, listener, uiScheduler, UtubotScheduler.mainThread());
    }

    /**
     * @param timer runs the waits of the transcript states (asking again, following a transcription)
     */
    public UtubotAnswerModel(Source source, Function<Insight, String> format, UtubotPanelModel.Listener listener, Scheduler uiScheduler,
                             UtubotScheduler timer) {
        mSource = source;
        mFormat = format;
        mListener = listener;
        mUiScheduler = uiScheduler;
        mTimer = timer;
        mRetryCountdown = new UtubotCountdown(timer, new UtubotCountdown.Listener() {
            @Override
            public void onTick(int remainingSec) {
                showRetryIn(remainingSec);
            }

            @Override
            public void onDone() {
                retry();
            }
        });
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
        cancel();
        mVideo = null;
        mState = null;
    }

    private void cancel() {
        mGeneration.invalidate();
        mActions.clear();
        mRetryCountdown.cancel();
        mTimer.remove(mPollTask);
    }

    private void load() {
        cancel();
        long token = mGeneration.begin();

        publish(Phase.LOADING, null, null, null);
        mActions.add(mSource.insightObserve(mVideo)
                .observeOn(mUiScheduler)
                .subscribe(insight -> {
                    if (mGeneration.isCurrent(token)) {
                        onInsight(insight);
                    }
                }, error -> {
                    if (mGeneration.isCurrent(token)) {
                        publish(Phase.FAILED, null, null, error.getMessage());
                    }
                }));
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
            mState = mState.withRetryIn(UtubotPanelModel.retrySeconds(insight.retryAfterSec));
            mListener.onState(mState);
            mRetryCountdown.start(mState.retryInSec);
        } else if (insight.isTranscribing()) {
            publishState(Phase.TRANSCRIBING, null, insight.source, null, null, insight);
            schedulePoll();
        } else if (insight.isPending()) {
            publish(Phase.PENDING, null, insight.source, null);
        } else {
            publish(Phase.READY, mFormat.apply(insight), insight.source, null);
        }
    }

    private void publishState(Phase phase, @Nullable String text, @Nullable String source, @Nullable String error, @Nullable String message,
                              Insight insight) {
        mState = new State(mVideo, phase, Collections.emptyList(), null, null, text, source, error, message, insight.canTranscribe,
                UtubotPanelModel.minutesOf(insight.estimateSec), insight.progressPercent, insight.reason);
        mListener.onState(mState);
    }

    private void publish(Phase phase, @Nullable String text, @Nullable String source, @Nullable String error) {
        mState = new State(mVideo, phase, Collections.emptyList(), null, null, text, source, error);
        mListener.onState(mState);
    }

    /**
     * One second of the wait before asking again has passed: the view shows what is left
     */
    private void showRetryIn(int remainingSec) {
        if (mState != null && mState.phase == Phase.DELAYED) {
            mState = mState.withRetryIn(remainingSec);
            mListener.onState(mState);
        }
    }

    private void schedulePoll() {
        mTimer.remove(mPollTask);
        mTimer.postDelayed(mPollTask, UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);
    }

    /**
     * Asks where the transcription stands: done means the answer can be asked for, a running one is followed, a failed one ends with its
     * error, and a job the backend forgot goes back to the answer, which says where things stand
     */
    private void pollTranscript() {
        Video video = mVideo;

        if (video == null) {
            return;
        }

        long token = mGeneration.begin();
        mActions.clear();
        mActions.add(mSource.transcriptObserve(video.videoId)
                .observeOn(mUiScheduler)
                .subscribe(transcript -> {
                    if (mGeneration.isCurrent(token)) {
                        onTranscript(transcript);
                    }
                }, error -> {
                    if (mGeneration.isCurrent(token)) {
                        publish(Phase.FAILED, null, null, error.getMessage());
                    }
                }));
    }

    private void onTranscript(Transcript transcript) {
        if (transcript.isFailed()) {
            publish(Phase.FAILED, null, null, transcript.error);
        } else if (transcript.isTranscribing()) {
            mState = new State(mVideo, Phase.TRANSCRIBING, Collections.emptyList(), null, null, null, null, null, null, false,
                    UtubotPanelModel.minutesOf(transcript.estimateSec), transcript.progressPercent);
            mListener.onState(mState);
            schedulePoll();
        } else {
            load();
        }
    }
}
