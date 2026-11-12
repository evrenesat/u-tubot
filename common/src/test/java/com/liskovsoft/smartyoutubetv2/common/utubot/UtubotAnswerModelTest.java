package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

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
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotAnswerModelTest {
    private final List<PublishSubject<Insight>> mCalls = new ArrayList<>();
    private final List<State> mStates = new ArrayList<>();
    private final UtubotAnswerModel mModel = new UtubotAnswerModel(video -> {
        PublishSubject<Insight> subject = PublishSubject.create();
        mCalls.add(subject);
        return (Observable<Insight>) subject;
    }, insight -> "answer: " + insight.answer, mStates::add, Schedulers.trampoline());

    private static Video video() {
        Video video = new Video();
        video.videoId = "aaaaaaaaaaa";
        video.title = "Does it work?";
        return video;
    }

    private State last() {
        return mStates.get(mStates.size() - 1);
    }

    private static Insight insight(String status, String answer) {
        Insight insight = new Insight();
        insight.status = status;
        insight.answer = answer;
        insight.source = "asr";
        return insight;
    }

    @Test
    public void loadingThenTheFormattedAnswer() {
        mModel.show(video());

        assertEquals(Phase.LOADING, last().phase);
        assertTrue(last().isWorking());
        assertEquals("Does it work?", last().video.title);

        mCalls.get(0).onNext(insight("ready", "yes"));

        assertEquals(Phase.READY, last().phase);
        assertEquals("answer: yes", last().text);
        assertEquals("asr", last().source);
        assertFalse(last().isWorking());
    }

    @Test
    public void failedAndPendingCanBeRetriedAndALateAnswerIsIgnored() {
        mModel.show(video());
        mCalls.get(0).onNext(insight("pending", null));
        assertEquals(Phase.PENDING, last().phase);
        assertTrue(last().canRetry());

        mModel.retry();
        assertEquals(2, mCalls.size());
        assertEquals(Phase.LOADING, last().phase);

        mCalls.get(1).onNext(insight("failed", null));
        assertEquals(Phase.FAILED, last().phase);

        mModel.retry();
        mCalls.get(2).onNext(insight("ready", "now"));
        assertEquals("answer: now", last().text);
    }

    @Test
    public void disposeDropsTheRequest() {
        mModel.show(video());
        int states = mStates.size();

        mModel.dispose();
        mCalls.get(0).onNext(insight("ready", "late"));

        assertEquals(states, mStates.size());
        assertFalse(mCalls.get(0).hasObservers());
    }

    @Test
    public void aTransportErrorIsAFailure() {
        mModel.show(video());
        mCalls.get(0).onError(new java.io.IOException("timeout"));

        assertEquals(Phase.FAILED, last().phase);
        assertEquals("timeout", last().error);
    }

    @Test
    public void anAnswerOfAVideoWithoutCaptionsIsNeverShownAsReadyWithNothingInIt() {
        mModel.show(video());
        Insight needs = insight("needs_transcript", null);
        needs.transcriptStatus = "none";
        needs.canTranscribe = true;
        needs.message = "No captions. Transcribe the audio in the background?";
        needs.estimateSec = 480;

        mCalls.get(0).onNext(needs);

        assertEquals(Phase.NEEDS_TRANSCRIPT, last().phase);
        assertEquals("No captions. Transcribe the audio in the background?", last().message);
        assertTrue(last().canTranscribe);
        assertEquals(8, last().estimateMinutes);
        assertEquals(UtubotPanelModel.Action.TRANSCRIBE, last().action());
    }

    @Test
    public void aDelayedAnswerShowsItsReasonAndCanBeAskedAgain() {
        mModel.show(video());
        Insight delayed = insight("pending", null);
        delayed.transcriptStatus = "delayed";
        delayed.error = "YouTube is limiting transcript downloads; retrying in ~5 min";
        delayed.retryAfterSec = 300;

        mCalls.get(0).onNext(delayed);

        assertEquals(Phase.DELAYED, last().phase);
        assertEquals("YouTube is limiting transcript downloads; retrying in ~5 min", last().message);
        assertEquals(UtubotPanelModel.Action.RETRY, last().action());
    }

    @Test
    public void aRunningTranscriptionShowsItsProgress() {
        mModel.show(video());
        Insight busy = insight("pending", null);
        busy.transcriptStatus = "transcribing";
        busy.progressPercent = 45;

        mCalls.get(0).onNext(busy);

        assertEquals(Phase.TRANSCRIBING, last().phase);
        assertEquals(45, last().progressPercent);
        assertTrue(last().isWorking());
    }

    @Test
    public void aFailureOfTheVideoOffersNoRetry() {
        mModel.show(video());
        Insight failed = insight("failed", null);
        failed.transcriptStatus = "failed";
        failed.error = "This video is private";
        failed.reason = "private";

        mCalls.get(0).onNext(failed);

        assertEquals(Phase.FAILED, last().phase);
        assertEquals(UtubotPanelModel.Action.NONE, last().action());
    }

    @Test
    public void theVideoOfTheAnswerIsKnownUntilItIsDisposed() {
        Video video = video();
        mModel.show(video);

        assertEquals(video, mModel.getVideo());

        mModel.dispose();
        assertEquals(null, mModel.getVideo());
    }
}
