package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;

import java.util.Collections;
import java.util.List;

import io.reactivex.Observable;
import io.reactivex.Scheduler;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.CompositeDisposable;

/**
 * What the summary views show for a video. The views only draw the state they are given.
 * <ul>
 * <li>{@link Mode#PANEL}: the passive side panel. It asks for the backend's panel prompt (prompt=panel); a backend that rejects
 * it gets the first prompt of its list instead. The title shows at once ({@link #waitFor}), the request starts later ({@link #show}).</li>
 * <li>{@link Mode#VIEW}: the Summary view. The prompt is the one picked for the session, else the backend's default; the user
 * moves between the prompts of the list.</li>
 * </ul>
 * Only the latest request counts: a card or a prompt the user has left is cancelled, and a late answer is ignored.
 * <p>
 * A video without a transcript is not an error: the backend says so ({@link Phase#NEEDS_TRANSCRIPT}: the user may start a background
 * transcription), that YouTube is slowing it down ({@link Phase#DELAYED}: the model asks again after the time it gives) or that a
 * transcription is running ({@link Phase#TRANSCRIBING}: the model follows its progress). These states are only held while the video
 * is shown: everything ends with {@link #dispose()} or the next card.
 */
public class UtubotPanelModel {
    public static final String PANEL_PROMPT = "panel";
    /** How often the progress of a running transcription is asked for in the Summary view, which the user watches */
    public static final long TRANSCRIPT_POLL_VIEW_MS = 4_000;
    /** The passive panel asks no faster than it did for a pending summary: one long poll of the backend (see UtubotManager.SUMMARY_WAIT_MS) */
    public static final long TRANSCRIPT_POLL_PANEL_MS = 20_000;
    /** The wait before asking again when the backend didn't say, and the bounds of what it says */
    public static final long DEFAULT_RETRY_MS = 10_000;
    public static final long MIN_RETRY_MS = 1_000;
    public static final long MAX_RETRY_MS = 10 * 60 * 1_000;
    private static final int SECONDS_PER_MINUTE = 60;
    private static final long MS_PER_SECOND = 1_000;

    public enum Mode {
        PANEL, VIEW
    }

    public enum Phase {
        IDLE,
        /** The title is up, the request waits for the user to stop moving */
        WAITING,
        LOADING,
        /** The backend is still working after the polls: ask again with Retry */
        PENDING,
        /** No captions: the user can have the audio transcribed in the background */
        NEEDS_TRANSCRIPT,
        /** YouTube is slowing the backend down: the model asks again by itself */
        DELAYED,
        /** A transcription is running */
        TRANSCRIBING,
        READY,
        FAILED
    }

    /**
     * What a view offers next: ask again, or have the audio transcribed
     */
    public enum Action {
        NONE, RETRY, TRANSCRIBE
    }

    public static final class State {
        public final Video video;
        public final Phase phase;
        public final List<Prompt> prompts;
        @Nullable public final String selectedKey;
        @Nullable public final String promptLabel;
        @Nullable public final String text;
        @Nullable public final String source;
        @Nullable public final String error;
        /** What the backend tells the user in {@link Phase#NEEDS_TRANSCRIPT} and {@link Phase#DELAYED} */
        @Nullable public final String message;
        /** The audio can be transcribed ({@link Phase#NEEDS_TRANSCRIPT}, or {@link Phase#FAILED} after a failed transcription) */
        public final boolean canTranscribe;
        /** The estimated time of a transcription in whole minutes, 0 when the backend didn't say */
        public final int estimateMinutes;
        /** 0 to 100, {@link UtubotModels#UNKNOWN} when not known */
        public final int progressPercent;
        /** Why the video can't be summarized at all ({@link Phase#FAILED}): asking again changes nothing */
        @Nullable public final String reason;
        /** The seconds left before a {@link Phase#DELAYED} request is asked again, {@link UtubotModels#UNKNOWN} otherwise */
        public final int retryInSec;

        State(Video video, Phase phase, List<Prompt> prompts, @Nullable String selectedKey, @Nullable String promptLabel, @Nullable String text,
              @Nullable String source, @Nullable String error) {
            this(video, phase, prompts, selectedKey, promptLabel, text, source, error, null, false, 0, UtubotModels.UNKNOWN);
        }

        State(Video video, Phase phase, List<Prompt> prompts, @Nullable String selectedKey, @Nullable String promptLabel, @Nullable String text,
              @Nullable String source, @Nullable String error, @Nullable String message, boolean canTranscribe, int estimateMinutes,
              int progressPercent) {
            this(video, phase, prompts, selectedKey, promptLabel, text, source, error, message, canTranscribe, estimateMinutes, progressPercent, null);
        }

        State(Video video, Phase phase, List<Prompt> prompts, @Nullable String selectedKey, @Nullable String promptLabel, @Nullable String text,
              @Nullable String source, @Nullable String error, @Nullable String message, boolean canTranscribe, int estimateMinutes,
              int progressPercent, @Nullable String reason) {
            this(video, phase, prompts, selectedKey, promptLabel, text, source, error, message, canTranscribe, estimateMinutes, progressPercent, reason,
                    UtubotModels.UNKNOWN);
        }

        State(Video video, Phase phase, List<Prompt> prompts, @Nullable String selectedKey, @Nullable String promptLabel, @Nullable String text,
              @Nullable String source, @Nullable String error, @Nullable String message, boolean canTranscribe, int estimateMinutes,
              int progressPercent, @Nullable String reason, int retryInSec) {
            this.video = video;
            this.phase = phase;
            this.prompts = prompts;
            this.selectedKey = selectedKey;
            this.promptLabel = promptLabel;
            this.text = text;
            this.source = source;
            this.error = error;
            this.message = message;
            this.canTranscribe = canTranscribe;
            this.estimateMinutes = estimateMinutes;
            this.progressPercent = progressPercent;
            this.reason = reason;
            this.retryInSec = retryInSec;
        }

        /**
         * The same state with another countdown
         */
        State withRetryIn(int seconds) {
            return new State(video, phase, prompts, selectedKey, promptLabel, text, source, error, message, canTranscribe, estimateMinutes, progressPercent,
                    reason, seconds);
        }

        /**
         * Working: the indicator is up
         */
        public boolean isWorking() {
            return phase == Phase.LOADING || phase == Phase.TRANSCRIBING;
        }

        /**
         * The user can ask again
         */
        public boolean canRetry() {
            return phase == Phase.FAILED || phase == Phase.PENDING || phase == Phase.DELAYED;
        }

        /**
         * The one thing a view with a button offers
         */
        public Action action() {
            if ((phase == Phase.NEEDS_TRANSCRIPT || phase == Phase.FAILED) && canTranscribe) {
                return Action.TRANSCRIBE;
            }

            // A problem of the video itself (private, live, too long...): nothing to try
            if (phase == Phase.FAILED && reason != null) {
                return Action.NONE;
            }

            return canRetry() ? Action.RETRY : Action.NONE;
        }
    }

    public interface Listener {
        void onState(State state);
    }

    public interface Source {
        @Nullable
        String getSessionPrompt();

        void setSessionPrompt(@Nullable String key);

        Observable<PromptList> promptsObserve(boolean forceReload);

        Observable<Summary> summaryObserve(Video video, @Nullable String promptKey);

        /** Starts the background transcription of a video without captions */
        Observable<Transcript> transcribeObserve(Video video);

        /** Where the transcript of a video stands */
        Observable<Transcript> transcriptObserve(String videoId);
    }

    private final Source mSource;
    private final Mode mMode;
    private final Listener mListener;
    private final Scheduler mUiScheduler;
    private final UtubotScheduler mTimer;
    private final RequestGeneration mGeneration = new RequestGeneration();
    private final UtubotCountdown mRetryCountdown;
    private final Runnable mPollTask = this::pollTranscript;
    /** The request the timers belong to: when it is outdated, a timer does nothing */
    private long mTimerToken;
    private Video mVideo;
    private List<Prompt> mPrompts = Collections.emptyList();
    private String mPanelDefaultKey;
    private String mSelectedKey;
    private String mFallbackKey;
    private State mState;
    private final CompositeDisposable mActions = new CompositeDisposable();

    public UtubotPanelModel(Source source, Mode mode, Listener listener) {
        this(source, mode, listener, AndroidSchedulers.mainThread(), UtubotScheduler.mainThread());
    }

    public UtubotPanelModel(Source source, Mode mode, Listener listener, Scheduler uiScheduler) {
        this(source, mode, listener, uiScheduler, UtubotScheduler.mainThread());
    }

    /**
     * @param timer runs the waits of the transcript states (asking again, following a transcription)
     */
    public UtubotPanelModel(Source source, Mode mode, Listener listener, Scheduler uiScheduler, UtubotScheduler timer) {
        mSource = source;
        mMode = mode;
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
                retryDelayed();
            }
        });
    }

    /**
     * Shows the video's title at once and drops whatever was loading before. The request starts with {@link #show}.
     */
    public void waitFor(Video video) {
        if (video == null || video.videoId == null) {
            return;
        }

        cancel();
        mVideo = video;
        publish(Phase.WAITING, null, null, null);
    }

    /**
     * Starts loading for the video, whatever was loading before is dropped
     */
    public void show(Video video) {
        if (video == null || video.videoId == null) {
            return;
        }

        cancel();
        mVideo = video;
        mSelectedKey = mMode == Mode.VIEW ? mSource.getSessionPrompt() : null;
        loadPrompts();
    }

    /**
     * Loads the summary of another prompt of the list (Summary view)
     */
    public void preview(String key) {
        if (mVideo == null || key == null || key.equals(mSelectedKey)) {
            return;
        }

        mSelectedKey = key;
        loadSummary(key);
    }

    /**
     * The prompt stays for the rest of the session, as the one the Summary view starts with
     */
    public void pin(String key) {
        if (key == null) {
            return;
        }

        mSource.setSessionPrompt(key);
        preview(key);
    }

    /**
     * Asks again after a failure or a pending answer
     */
    public void retry() {
        if (mVideo == null) {
            return;
        }

        if (mMode == Mode.VIEW && mPrompts.isEmpty()) {
            loadPrompts();
        } else {
            loadSummary(requestKey());
        }
    }

    /**
     * Has the audio of the video transcribed in the background (it has no captions). The progress shows while the view is up.
     */
    public void transcribe() {
        if (mVideo == null) {
            return;
        }

        long token = mGeneration.begin();
        mActions.clear();
        removeTimers();
        publishTranscribing(UtubotModels.UNKNOWN, 0);
        mActions.add(mSource.transcribeObserve(mVideo)
                .observeOn(mUiScheduler)
                .subscribe(transcript -> {
                    if (mGeneration.isCurrent(token)) {
                        onTranscript(token, transcript);
                    }
                }, error -> {
                    if (mGeneration.isCurrent(token)) {
                        publish(Phase.FAILED, null, null, error.getMessage());
                    }
                }));
    }

    /**
     * Drops what is loading and forgets the video
     */
    public void dispose() {
        cancel();
        mVideo = null;
        mState = null;
    }

    @Nullable
    public Video getVideo() {
        return mVideo;
    }

    @Nullable
    public String getSelectedKey() {
        return mSelectedKey;
    }

    @Nullable
    public State getState() {
        return mState;
    }

    private void cancel() {
        mGeneration.invalidate();
        mActions.clear();
        removeTimers();
    }

    private void removeTimers() {
        mRetryCountdown.cancel();
        mTimer.remove(mPollTask);
    }

    private void loadPrompts() {
        long token = mGeneration.begin();
        publish(Phase.LOADING, null, null, null);
        mActions.add(mSource.promptsObserve(false)
                .observeOn(mUiScheduler)
                .subscribe(list -> {
                    if (mGeneration.isCurrent(token)) {
                        onPrompts(list);
                    }
                }, error -> {
                    // The summary of the backend's own choice still works without the list
                    if (mGeneration.isCurrent(token)) {
                        mPrompts = Collections.emptyList();
                        loadSummary(requestKey());
                    }
                }));
    }

    private void onPrompts(PromptList list) {
        mPrompts = list.allPrompts();
        mPanelDefaultKey = list.panelDefaultKey;

        if (mMode == Mode.VIEW && (mSelectedKey == null || list.find(mSelectedKey) == null)) {
            mSelectedKey = list.defaultKey;
        }

        loadSummary(requestKey());
    }

    /**
     * What the request names: the panel prompt, or the prompt of the Summary view (null: the backend's default)
     */
    @Nullable
    private String requestKey() {
        if (mMode == Mode.PANEL) {
            return mFallbackKey != null ? mFallbackKey : PANEL_PROMPT;
        }

        return mSelectedKey;
    }

    private void loadSummary(@Nullable String key) {
        Video video = mVideo;
        long token = mGeneration.begin();

        mActions.clear();
        removeTimers();
        publish(Phase.LOADING, null, null, null);
        mActions.add(mSource.summaryObserve(video, key)
                .observeOn(mUiScheduler)
                .subscribe(summary -> {
                    if (mGeneration.isCurrent(token)) {
                        onSummary(token, summary);
                    }
                }, error -> {
                    if (mGeneration.isCurrent(token)) {
                        onError(key, error);
                    }
                }));
    }

    private void onError(@Nullable String key, Throwable error) {
        Prompt fallback = mPrompts.isEmpty() ? null : mPrompts.get(0);

        if (mMode == Mode.PANEL && PANEL_PROMPT.equals(key) && isPromptRejected(error) && fallback != null) {
            mFallbackKey = fallback.key;
            loadSummary(mFallbackKey);
            return;
        }

        publish(Phase.FAILED, null, null, error.getMessage());
    }

    private static boolean isPromptRejected(Throwable error) {
        return error instanceof UtubotClient.HttpException && ((UtubotClient.HttpException) error).isPromptRejected();
    }

    private void onSummary(long token, Summary summary) {
        if (summary.isFailed()) {
            publishFailed(summary);
        } else if (summary.needsTranscript()) {
            publishNeedsTranscript(summary);
        } else if (summary.isDelayed()) {
            publishDelayed(token, summary);
        } else if (summary.isTranscribing()) {
            publishTranscribing(summary.progressPercent, minutesOf(summary.estimateSec));
            schedulePoll(token);
        } else if (summary.isPending()) {
            publish(Phase.PENDING, null, summary.source, null);
        } else {
            publish(Phase.READY, summary.text, summary.source, null);
        }
    }

    private void publishFailed(Summary summary) {
        mState = new State(mVideo, Phase.FAILED, mPrompts, selectedKeyOf(), labelOf(labelKey()), null, summary.source, summary.error, null,
                summary.canTranscribe, minutesOf(summary.estimateSec), UtubotModels.UNKNOWN, summary.reason);
        mListener.onState(mState);
    }

    private void publishNeedsTranscript(Summary summary) {
        mState = new State(mVideo, Phase.NEEDS_TRANSCRIPT, mPrompts, selectedKeyOf(), labelOf(labelKey()), null, summary.source, null, summary.message,
                summary.canTranscribe, minutesOf(summary.estimateSec), UtubotModels.UNKNOWN);
        mListener.onState(mState);
    }

    private void publishDelayed(long token, Summary summary) {
        String message = summary.message != null ? summary.message : summary.error;
        mState = new State(mVideo, Phase.DELAYED, mPrompts, selectedKeyOf(), labelOf(labelKey()), null, summary.source, null, message, false, 0,
                UtubotModels.UNKNOWN);
        mListener.onState(mState);
        mTimerToken = token;
        mState = mState.withRetryIn(retrySeconds(summary.retryAfterSec));
        mListener.onState(mState);
        mRetryCountdown.start(mState.retryInSec);
    }

    private void publishTranscribing(int progressPercent, int estimateMinutes) {
        mState = new State(mVideo, Phase.TRANSCRIBING, mPrompts, selectedKeyOf(), labelOf(labelKey()), null, null, null, null, false, estimateMinutes,
                progressPercent);
        mListener.onState(mState);
    }

    /**
     * One second of the wait has passed: the views show what is left
     */
    private void showRetryIn(int remainingSec) {
        if (mState != null && mState.phase == Phase.DELAYED && mGeneration.isCurrent(mTimerToken)) {
            mState = mState.withRetryIn(remainingSec);
            mListener.onState(mState);
        }
    }

    /**
     * The backend said "try again in N seconds": the wait is kept inside bounds, and nothing happens once the card or view is gone
     */
    private void retryDelayed() {
        if (mVideo != null && mGeneration.isCurrent(mTimerToken)) {
            loadSummary(requestKey());
        }
    }

    private void schedulePoll(long token) {
        mTimerToken = token;
        mTimer.remove(mPollTask);
        mTimer.postDelayed(mPollTask, mMode == Mode.PANEL ? TRANSCRIPT_POLL_PANEL_MS : TRANSCRIPT_POLL_VIEW_MS);
    }

    private void pollTranscript() {
        Video video = mVideo;
        long token = mTimerToken;

        if (video == null || !mGeneration.isCurrent(token)) {
            return;
        }

        mActions.add(mSource.transcriptObserve(video.videoId)
                .observeOn(mUiScheduler)
                .subscribe(transcript -> {
                    if (mGeneration.isCurrent(token)) {
                        onTranscript(token, transcript);
                    }
                }, error -> {
                    if (mGeneration.isCurrent(token)) {
                        publish(Phase.FAILED, null, null, error.getMessage());
                    }
                }));
    }

    /**
     * The transcript state of a started or running transcription: done means the summary can be asked for, failed ends it, a running
     * one is followed. Any other state (the backend forgot the job) goes back to the summary, which says where things stand.
     */
    private void onTranscript(long token, Transcript transcript) {
        if (transcript.isDone()) {
            reload();
        } else if (transcript.isFailed()) {
            publish(Phase.FAILED, null, null, transcript.error);
        } else if (transcript.isTranscribing()) {
            publishTranscribing(transcript.progressPercent, minutesOf(transcript.estimateSec));
            schedulePoll(token);
        } else {
            reload();
        }
    }

    /**
     * Asks for the summary again; the Summary view that was started on a transcription has no prompt list yet
     */
    private void reload() {
        if (mMode == Mode.VIEW && mPrompts.isEmpty()) {
            loadPrompts();
        } else {
            loadSummary(requestKey());
        }
    }

    /**
     * The seconds to wait before asking again: what the backend said, within bounds
     */
    static int retrySeconds(int retryAfterSec) {
        long delayMs = retryAfterSec == UtubotModels.UNKNOWN ? DEFAULT_RETRY_MS : retryAfterSec * MS_PER_SECOND;

        return (int) (Math.max(MIN_RETRY_MS, Math.min(MAX_RETRY_MS, delayMs)) / MS_PER_SECOND);
    }

    static int minutesOf(int seconds) {
        return seconds == UtubotModels.UNKNOWN ? 0 : Math.max(1, (seconds + SECONDS_PER_MINUTE - 1) / SECONDS_PER_MINUTE);
    }

    @Nullable
    private String selectedKeyOf() {
        return mMode == Mode.VIEW ? mSelectedKey : labelKey();
    }

    /**
     * The key of the prompt the header names: the picked one, or in the panel the panel prompt (or the fallback)
     */
    @Nullable
    private String labelKey() {
        if (mMode == Mode.VIEW) {
            return mSelectedKey;
        }

        return mFallbackKey != null ? mFallbackKey : mPanelDefaultKey;
    }

    @Nullable
    private String labelOf(@Nullable String key) {
        if (key == null) {
            return null;
        }

        for (Prompt prompt : mPrompts) {
            if (key.equals(prompt.key)) {
                return prompt.label;
            }
        }

        return null;
    }

    private void publish(Phase phase, @Nullable String text, @Nullable String source, @Nullable String error) {
        String key = labelKey();
        mState = new State(mVideo, phase, mPrompts, mMode == Mode.VIEW ? mSelectedKey : key, labelOf(key), text, source, error);
        mListener.onState(mState);
    }
}
