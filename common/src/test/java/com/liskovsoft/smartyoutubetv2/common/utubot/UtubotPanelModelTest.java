package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Mode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.List;

import io.reactivex.Observable;
import io.reactivex.schedulers.Schedulers;
import io.reactivex.subjects.PublishSubject;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotPanelModelTest {
    private static final String SECOND_PROMPT = "builtin/tldr";
    private static final String GLANCE_PROMPT = "builtin/glance";

    private static final class Call {
        final String videoId;
        final String promptKey;
        final PublishSubject<Summary> answer = PublishSubject.create();

        Call(String videoId, String promptKey) {
            this.videoId = videoId;
            this.promptKey = promptKey;
        }
    }

    private static final class FakeSource implements UtubotPanelModel.Source {
        final List<Call> calls = new ArrayList<>();
        PromptList prompts = promptList(GLANCE_PROMPT);
        String sessionPrompt;
        boolean promptsFail;
        final List<String> transcribes = new ArrayList<>();
        final List<Transcript> pollAnswers = new ArrayList<>();
        Observable<Transcript> transcribeAnswer = Observable.never();
        int polls;

        @Nullable
        @Override
        public String getSessionPrompt() {
            return sessionPrompt;
        }

        @Override
        public void setSessionPrompt(@Nullable String key) {
            sessionPrompt = key;
        }

        @Override
        public Observable<PromptList> promptsObserve(boolean forceReload) {
            return promptsFail ? Observable.error(new java.io.IOException("down")) : Observable.just(prompts);
        }

        @Override
        public Observable<Summary> summaryObserve(Video video, @Nullable String promptKey) {
            Call call = new Call(video.videoId, promptKey);
            calls.add(call);
            return call.answer;
        }

        @Override
        public Observable<Transcript> transcribeObserve(Video video) {
            transcribes.add(video.videoId);
            return transcribeAnswer;
        }

        @Override
        public Observable<Transcript> transcriptObserve(String videoId) {
            polls++;
            return pollAnswers.isEmpty() ? Observable.never() : Observable.just(pollAnswers.remove(0));
        }

        Call last() {
            return calls.get(calls.size() - 1);
        }
    }

    private final FakeSource mSource = new FakeSource();
    private final FakeScheduler mTimer = new FakeScheduler();
    private final List<State> mStates = new ArrayList<>();
    private UtubotPanelModel mPanel;
    private UtubotPanelModel mView;

    @Before
    public void setUp() {
        mPanel = new UtubotPanelModel(mSource, Mode.PANEL, mStates::add, Schedulers.trampoline(), mTimer);
        mView = new UtubotPanelModel(mSource, Mode.VIEW, mStates::add, Schedulers.trampoline(), mTimer);
    }

    private static PromptList promptList(@Nullable String panelDefault) {
        PromptList list = new PromptList();
        list.defaultKey = SECOND_PROMPT;
        list.panelDefaultKey = panelDefault;
        PromptSet set = new PromptSet();
        set.id = "builtin";
        set.prompts.add(prompt("builtin/short", "Short"));
        set.prompts.add(prompt(SECOND_PROMPT, "TL;DR"));
        set.prompts.add(prompt(GLANCE_PROMPT, "Glance"));
        list.sets.add(set);
        return list;
    }

    private static Prompt prompt(String key, String label) {
        Prompt prompt = new Prompt();
        prompt.id = key.substring(key.indexOf('/') + 1);
        prompt.key = key;
        prompt.label = label;
        return prompt;
    }

    private static Video video(String id, String title) {
        Video video = new Video();
        video.videoId = id;
        video.title = title;
        return video;
    }

    private static Summary ready(String text) {
        Summary summary = new Summary();
        summary.status = "ready";
        summary.text = text;
        summary.source = "youtube_captions";
        return summary;
    }

    private State lastState() {
        return mStates.get(mStates.size() - 1);
    }

    @Test
    public void panelWaitsWithTheTitleBeforeAnyRequest() {
        mPanel.waitFor(video("aaaaaaaaaaa", "First"));

        assertEquals(Phase.WAITING, lastState().phase);
        assertEquals("First", lastState().video.title);
        assertTrue(mSource.calls.isEmpty());
    }

    @Test
    public void panelAsksForThePanelPromptAndNamesItsLabel() {
        mPanel.show(video("aaaaaaaaaaa", "First"));

        assertEquals(UtubotPanelModel.PANEL_PROMPT, mSource.last().promptKey);
        assertEquals("panel", mSource.last().promptKey);
        assertEquals(Phase.LOADING, lastState().phase);
        assertEquals("Glance", lastState().promptLabel);

        mSource.last().answer.onNext(ready("→ Yes.\nBecause."));

        assertEquals(Phase.READY, lastState().phase);
        assertEquals("→ Yes.\nBecause.", lastState().text);
        assertEquals("Glance", lastState().promptLabel);
    }

    @Test
    public void panelIgnoresTheSessionPromptOfTheView() {
        mSource.sessionPrompt = SECOND_PROMPT;

        mPanel.show(video("aaaaaaaaaaa", "First"));

        assertEquals("panel", mSource.last().promptKey);
    }

    @Test
    public void panelFallsBackToTheFirstPromptWhenTheBackendRejectsThePanelPrompt() {
        mSource.prompts = promptList(null);
        mPanel.show(video("aaaaaaaaaaa", "First"));
        assertEquals("panel", mSource.last().promptKey);

        mSource.last().answer.onError(new UtubotClient.HttpException(404, "HTTP 404"));

        assertEquals(2, mSource.calls.size());
        assertEquals("builtin/short", mSource.last().promptKey);
        assertEquals(Phase.LOADING, lastState().phase);
        assertEquals("Short", lastState().promptLabel);

        mSource.last().answer.onNext(ready("text"));
        assertEquals(Phase.READY, lastState().phase);
        assertEquals("Short", lastState().promptLabel);
    }

    @Test
    public void panelFallsBackOnA400Too() {
        mSource.prompts = promptList(null);
        mPanel.show(video("aaaaaaaaaaa", "First"));

        mSource.last().answer.onError(new UtubotClient.HttpException(400, "HTTP 400"));

        assertEquals("builtin/short", mSource.last().promptKey);
    }

    @Test
    public void panelRemembersTheFallbackForTheNextCards() {
        mSource.prompts = promptList(null);
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onError(new UtubotClient.HttpException(404, "HTTP 404"));
        mSource.last().answer.onNext(ready("text"));

        mPanel.show(video("bbbbbbbbbbb", "Second"));

        assertEquals("bbbbbbbbbbb", mSource.last().videoId);
        assertEquals("builtin/short", mSource.last().promptKey);
        assertEquals(3, mSource.calls.size());
    }

    @Test
    public void panelDoesNotFallBackOnOtherErrors() {
        mSource.prompts = promptList(null);
        mPanel.show(video("aaaaaaaaaaa", "First"));

        mSource.last().answer.onError(new UtubotClient.HttpException(500, "HTTP 500: boom"));

        assertEquals(1, mSource.calls.size());
        assertEquals(Phase.FAILED, lastState().phase);
        assertEquals("HTTP 500: boom", lastState().error);
    }

    @Test
    public void panelWithoutAPromptListFailsWhenThePanelPromptIsRejected() {
        mSource.promptsFail = true;
        mPanel.show(video("aaaaaaaaaaa", "First"));
        assertEquals("panel", mSource.last().promptKey);

        mSource.last().answer.onError(new UtubotClient.HttpException(404, "HTTP 404"));

        assertEquals(1, mSource.calls.size());
        assertEquals(Phase.FAILED, lastState().phase);
    }

    @Test
    public void aCardTheUserLeftDoesNotOverwriteThePanel() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        Call first = mSource.last();

        mPanel.waitFor(video("bbbbbbbbbbb", "Second"));
        mPanel.show(video("bbbbbbbbbbb", "Second"));
        Call second = mSource.last();

        first.answer.onNext(ready("the first summary"));

        assertFalse(first.answer.hasObservers());
        assertEquals(Phase.LOADING, lastState().phase);
        assertEquals("Second", lastState().video.title);

        second.answer.onNext(ready("the second summary"));

        assertEquals("the second summary", lastState().text);
        assertEquals("Second", lastState().video.title);
    }

    @Test
    public void disposeDropsTheRequestInFlight() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        Call call = mSource.last();
        int states = mStates.size();

        mPanel.dispose();
        call.answer.onNext(ready("late"));

        assertEquals(states, mStates.size());
        assertFalse(call.answer.hasObservers());
        assertNull(mPanel.getVideo());
    }

    @Test
    public void pendingAndFailedAnswersOfTheBackendCanBeRetried() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        Summary pending = new Summary();
        mSource.last().answer.onNext(pending);

        assertEquals(Phase.PENDING, lastState().phase);
        assertTrue(lastState().canRetry());
        assertFalse(lastState().isWorking());

        mPanel.retry();
        assertEquals(2, mSource.calls.size());
        assertTrue(lastState().isWorking());

        Summary failed = new Summary();
        failed.status = "failed";
        failed.error = "no captions";
        mSource.last().answer.onNext(failed);

        assertEquals(Phase.FAILED, lastState().phase);
        assertEquals("no captions", lastState().error);
        assertTrue(lastState().canRetry());
    }

    @Test
    public void viewStartsWithTheBackendsDefaultAndTheWholeList() {
        mView.show(video("aaaaaaaaaaa", "First"));

        assertEquals(SECOND_PROMPT, mSource.last().promptKey);
        assertEquals(SECOND_PROMPT, lastState().selectedKey);
        assertEquals("TL;DR", lastState().promptLabel);
        assertEquals(3, lastState().prompts.size());
    }

    @Test
    public void viewStartsWithThePromptKeptForTheSession() {
        mSource.sessionPrompt = "builtin/short";

        mView.show(video("aaaaaaaaaaa", "First"));

        assertEquals("builtin/short", mSource.last().promptKey);
        assertEquals("Short", lastState().promptLabel);
    }

    @Test
    public void viewPreviewCancelsTheLoadingOfThePromptLeftAndIgnoresItsLateAnswer() {
        mView.show(video("aaaaaaaaaaa", "First"));
        Call first = mSource.last();

        mView.preview("builtin/short");
        Call second = mSource.last();
        assertEquals("builtin/short", second.promptKey);
        assertFalse(first.answer.hasObservers());

        first.answer.onNext(ready("late TL;DR"));
        assertEquals(Phase.LOADING, lastState().phase);

        second.answer.onNext(ready("short one"));
        assertEquals("short one", lastState().text);
        assertEquals("Short", lastState().promptLabel);
    }

    @Test
    public void viewPreviewDoesNotPinButPinKeepsThePromptForTheSession() {
        mView.show(video("aaaaaaaaaaa", "First"));

        mView.preview("builtin/short");
        assertNull(mSource.sessionPrompt);

        mView.pin("builtin/short");
        assertEquals("builtin/short", mSource.sessionPrompt);
        assertEquals(2, mSource.calls.size());

        mView.pin(GLANCE_PROMPT);
        assertEquals(GLANCE_PROMPT, mSource.sessionPrompt);
        assertEquals(GLANCE_PROMPT, mSource.last().promptKey);
    }

    @Test
    public void viewPreviewOfTheLoadedPromptDoesNothing() {
        mView.show(video("aaaaaaaaaaa", "First"));
        int calls = mSource.calls.size();

        mView.preview(SECOND_PROMPT);

        assertEquals(calls, mSource.calls.size());
    }

    @Test
    public void viewRetryWithoutAListLoadsTheListAgain() {
        mSource.promptsFail = true;
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onError(new java.io.IOException("down"));
        assertEquals(Phase.FAILED, lastState().phase);
        assertTrue(lastState().prompts.isEmpty());

        mSource.promptsFail = false;
        mView.retry();

        assertEquals(SECOND_PROMPT, mSource.last().promptKey);
        assertEquals(3, lastState().prompts.size());
    }

    // Transcript states

    private static Summary needsTranscript(boolean canTranscribe, int estimateSec) {
        Summary summary = new Summary();
        summary.status = "needs_transcript";
        summary.transcriptStatus = "none";
        summary.canTranscribe = canTranscribe;
        summary.message = "No captions. Transcribe the audio in the background?";
        summary.estimateSec = estimateSec;
        return summary;
    }

    private static Summary delayed(int retryAfterSec) {
        Summary summary = new Summary();
        summary.status = "pending";
        summary.transcriptStatus = "delayed";
        summary.error = "YouTube is slowing us down";
        summary.retryAfterSec = retryAfterSec;
        return summary;
    }

    private static Summary transcribing(int progressPercent) {
        Summary summary = new Summary();
        summary.status = "pending";
        summary.transcriptStatus = "transcribing";
        summary.progressPercent = progressPercent;
        summary.estimateSec = 240;
        return summary;
    }

    private static Transcript transcript(String status, int progressPercent) {
        Transcript transcript = new Transcript();
        transcript.status = status;
        transcript.progressPercent = progressPercent;
        return transcript;
    }

    @Test
    public void aVideoWithoutCaptionsOffersTheTranscriptionWithItsEstimate() {
        mView.show(video("aaaaaaaaaaa", "First"));

        mSource.last().answer.onNext(needsTranscript(true, 241));

        State state = lastState();
        assertEquals(Phase.NEEDS_TRANSCRIPT, state.phase);
        assertEquals("No captions. Transcribe the audio in the background?", state.message);
        assertTrue(state.canTranscribe);
        assertEquals(5, state.estimateMinutes);
        assertEquals(UtubotPanelModel.Action.TRANSCRIBE, state.action());
        assertFalse(state.isWorking());
        assertNull(state.text);
    }

    @Test
    public void aVideoThatCannotBeTranscribedOffersNothing() {
        mView.show(video("aaaaaaaaaaa", "First"));

        mSource.last().answer.onNext(needsTranscript(false, UtubotModels.UNKNOWN));

        assertEquals(Phase.NEEDS_TRANSCRIPT, lastState().phase);
        assertFalse(lastState().canTranscribe);
        assertEquals(UtubotPanelModel.Action.NONE, lastState().action());
        assertEquals(0, lastState().estimateMinutes);
    }

    @Test
    public void theTranscriptStatusAloneIsEnoughToNeedATranscript() {
        Summary summary = new Summary();
        summary.status = "pending";
        summary.transcriptStatus = "none";

        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(summary);

        assertEquals(Phase.NEEDS_TRANSCRIPT, lastState().phase);
    }

    @Test
    public void aDelayedAnswerShowsTheMessageAndAsksAgainAfterTheTimeTheBackendGave() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(30));

        assertEquals(Phase.DELAYED, lastState().phase);
        assertEquals("YouTube is slowing us down", lastState().message);
        assertEquals(UtubotPanelModel.Action.RETRY, lastState().action());
        assertEquals(1, mSource.calls.size());

        mTimer.advance(29_000);
        assertEquals(1, mSource.calls.size());

        mTimer.advance(1_000);
        assertEquals(2, mSource.calls.size());
        assertEquals("panel", mSource.last().promptKey);
        assertEquals(Phase.LOADING, lastState().phase);

        mSource.last().answer.onNext(ready("→ Yes."));
        assertEquals(Phase.READY, lastState().phase);
    }

    @Test
    public void aDelayedAnswerKeepsAskingWhileItStaysDelayed() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(5));
        mTimer.advance(5_000);
        mSource.last().answer.onNext(delayed(5));

        assertEquals(Phase.DELAYED, lastState().phase);
        mTimer.advance(5_000);

        assertEquals(3, mSource.calls.size());
    }

    @Test
    public void theWaitBeforeAskingAgainStaysWithinBounds() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(0));
        mTimer.advance(UtubotPanelModel.MIN_RETRY_MS - 1);
        assertEquals(1, mSource.calls.size());
        mTimer.advance(1);
        assertEquals(2, mSource.calls.size());

        mSource.last().answer.onNext(delayed(100_000));
        mTimer.advance(UtubotPanelModel.MAX_RETRY_MS - 1);
        assertEquals(2, mSource.calls.size());
        mTimer.advance(1);
        assertEquals(3, mSource.calls.size());

        Summary unsaid = delayed(UtubotModels.UNKNOWN);
        mSource.last().answer.onNext(unsaid);
        mTimer.advance(UtubotPanelModel.DEFAULT_RETRY_MS);
        assertEquals(4, mSource.calls.size());
    }

    @Test
    public void aDelayedCardTheUserLeftIsNotAskedAgain() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(5));

        mPanel.waitFor(video("bbbbbbbbbbb", "Second"));
        mTimer.advance(60_000);

        assertEquals(1, mSource.calls.size());
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void aDelayedCardThatWasHiddenIsNotAskedAgain() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(5));

        mPanel.dispose();
        mTimer.advance(60_000);

        assertEquals(1, mSource.calls.size());
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void theViewIsNotAskedAgainAfterItClosed() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(5));

        mView.dispose();
        mTimer.advance(60_000);

        assertEquals(1, mSource.calls.size());
    }

    @Test
    public void retryNowAsksAtOnceAndCancelsTheWait() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(delayed(60));

        mView.retry();

        assertEquals(2, mSource.calls.size());
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void aRunningTranscriptionShowsItsProgressAndFollowsIt() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(35));

        State state = lastState();
        assertEquals(Phase.TRANSCRIBING, state.phase);
        assertEquals(35, state.progressPercent);
        assertTrue(state.isWorking());
        assertEquals(UtubotPanelModel.Action.NONE, state.action());

        mSource.pollAnswers.add(transcript("transcribing", 60));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);

        assertEquals(1, mSource.polls);
        assertEquals(60, lastState().progressPercent);
        assertEquals(Phase.TRANSCRIBING, lastState().phase);

        mSource.pollAnswers.add(transcript("transcribing", 90));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);
        assertEquals(90, lastState().progressPercent);
    }

    @Test
    public void aFinishedTranscriptionLoadsTheSummary() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(80));
        int callsBefore = mSource.calls.size();

        mSource.pollAnswers.add(transcript("ok", UtubotModels.UNKNOWN));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);

        assertEquals(callsBefore + 1, mSource.calls.size());
        assertEquals(Phase.LOADING, lastState().phase);
        mSource.last().answer.onNext(ready("The long summary"));
        assertEquals(Phase.READY, lastState().phase);
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void aFailedTranscriptionEndsWithItsError() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(10));

        Transcript failed = transcript("failed", UtubotModels.UNKNOWN);
        failed.error = "transcription failed";
        mSource.pollAnswers.add(failed);
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);

        assertEquals(Phase.FAILED, lastState().phase);
        assertEquals("transcription failed", lastState().error);
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void aTranscriptionTheBackendForgotGoesBackToTheSummary() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(10));
        int callsBefore = mSource.calls.size();

        mSource.pollAnswers.add(transcript("unknown", UtubotModels.UNKNOWN));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);

        assertEquals(callsBefore + 1, mSource.calls.size());
    }

    @Test
    public void followingATranscriptionStopsWithTheCard() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(10));

        mPanel.waitFor(video("bbbbbbbbbbb", "Second"));
        mTimer.advance(60_000);

        assertEquals(0, mSource.polls);
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void aPollAnswerOfACardTheUserLeftIsIgnored() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(10));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_PANEL_MS);
        assertEquals(1, mSource.polls);

        mPanel.waitFor(video("bbbbbbbbbbb", "Second"));

        assertEquals(Phase.WAITING, lastState().phase);
        assertEquals("Second", lastState().video.title);
    }

    @Test
    public void theTranscribeActionStartsTheJobThenFollowsItsProgress() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(needsTranscript(true, 240));
        mSource.transcribeAnswer = Observable.just(transcript("transcribing", 0));

        mView.transcribe();

        assertEquals(1, mSource.transcribes.size());
        assertEquals("aaaaaaaaaaa", mSource.transcribes.get(0));
        assertEquals(Phase.TRANSCRIBING, lastState().phase);
        assertEquals(0, lastState().progressPercent);

        mSource.pollAnswers.add(transcript("transcribing", 25));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);
        assertEquals(25, lastState().progressPercent);

        mSource.pollAnswers.add(transcript("ok", UtubotModels.UNKNOWN));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);
        assertEquals(Phase.LOADING, lastState().phase);
    }

    @Test
    public void theTranscribeActionShowsTheIndicatorAtOnceAndFailsWithTheServersReason() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(needsTranscript(true, 240));
        PublishSubject<Transcript> answer = PublishSubject.create();
        mSource.transcribeAnswer = answer;

        mView.transcribe();
        assertEquals(Phase.TRANSCRIBING, lastState().phase);
        assertTrue(lastState().isWorking());

        answer.onError(new UtubotClient.HttpException(429, "HTTP 429: too many transcriptions queued"));

        assertEquals(Phase.FAILED, lastState().phase);
        assertEquals("HTTP 429: too many transcriptions queued", lastState().error);
        assertEquals(UtubotPanelModel.Action.RETRY, lastState().action());
    }

    @Test
    public void closingTheViewDuringTheTranscribeCallDropsItsAnswer() {
        mView.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(needsTranscript(true, 240));
        PublishSubject<Transcript> answer = PublishSubject.create();
        mSource.transcribeAnswer = answer;
        mView.transcribe();
        int states = mStates.size();

        mView.dispose();

        assertFalse(answer.hasObservers());
        assertEquals(states, mStates.size());
        assertEquals(0, mTimer.pending());
    }

    @Test
    public void transcribeWithoutAVideoDoesNothing() {
        mView.transcribe();

        assertTrue(mSource.transcribes.isEmpty());
        assertTrue(mStates.isEmpty());
    }

    @Test
    public void thePassivePanelAsksForTheProgressNoFasterThanOneLongPoll() {
        mPanel.show(video("aaaaaaaaaaa", "First"));
        mSource.last().answer.onNext(transcribing(10));

        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_PANEL_MS - 1);
        assertEquals(0, mSource.polls);

        mSource.pollAnswers.add(transcript("transcribing", 20));
        mTimer.advance(1);
        assertEquals(1, mSource.polls);
        assertEquals(20, lastState().progressPercent);
        assertTrue(UtubotPanelModel.TRANSCRIPT_POLL_PANEL_MS >= UtubotManager.SUMMARY_WAIT_MS);
    }

    @Test
    public void aFailedTranscriptionThatMayBeTriedAgainOffersTheTranscription() {
        mView.show(video("aaaaaaaaaaa", "First"));
        Summary failed = new Summary();
        failed.status = "failed";
        failed.transcriptStatus = "failed";
        failed.error = "transcription failed";
        failed.canTranscribe = true;
        failed.estimateSec = 300;

        mSource.last().answer.onNext(failed);

        assertEquals(Phase.FAILED, lastState().phase);
        assertEquals("transcription failed", lastState().error);
        assertEquals(UtubotPanelModel.Action.TRANSCRIBE, lastState().action());
        assertEquals(5, lastState().estimateMinutes);
    }

    @Test
    public void aProblemOfTheVideoItselfOffersNothingToTry() {
        mView.show(video("aaaaaaaaaaa", "First"));
        Summary failed = new Summary();
        failed.status = "failed";
        failed.transcriptStatus = "failed";
        failed.error = "This video is private";
        failed.reason = "private";

        mSource.last().answer.onNext(failed);

        assertEquals(Phase.FAILED, lastState().phase);
        assertEquals("private", lastState().reason);
        assertEquals(UtubotPanelModel.Action.NONE, lastState().action());
    }

    @Test
    public void aFailureOfTheModelCanStillBeRetried() {
        mView.show(video("aaaaaaaaaaa", "First"));
        Summary failed = new Summary();
        failed.status = "failed";
        failed.error = "the language model request failed, try again later";

        mSource.last().answer.onNext(failed);

        assertEquals(UtubotPanelModel.Action.RETRY, lastState().action());
    }

    @Test
    public void aViewStartedOnATranscriptionLoadsItsPromptsWhenTheTranscriptIsDone() {
        mView.waitFor(video("aaaaaaaaaaa", "First"));
        mSource.transcribeAnswer = Observable.just(transcript("transcribing", 0));
        mView.transcribe();

        mSource.pollAnswers.add(transcript("ok", UtubotModels.UNKNOWN));
        mTimer.advance(UtubotPanelModel.TRANSCRIPT_POLL_VIEW_MS);

        // The list of prompts comes first, then the summary of the one the view starts with
        assertEquals(1, mSource.calls.size());
        assertEquals(SECOND_PROMPT, mSource.last().promptKey);
        assertEquals(3, lastState().prompts.size());
    }
}
