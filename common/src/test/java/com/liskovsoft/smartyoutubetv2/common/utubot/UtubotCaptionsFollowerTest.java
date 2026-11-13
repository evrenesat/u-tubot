package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;

import org.junit.Before;
import org.junit.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedList;
import java.util.List;
import java.util.Queue;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotCaptionsFollowerTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String OTHER_VIDEO = "jNQXAC9IVRw";

    private final FakeScheduler mScheduler = new FakeScheduler();
    private final Queue<Object> mAnswers = new LinkedList<>();
    private final List<String> mFetched = new ArrayList<>();
    private final List<String> mReady = new ArrayList<>();
    private final List<Boolean> mRequested = new ArrayList<>();
    private UtubotCaptionsFollower mFollower;
    private final UtubotCaptionsFollower.Listener mListener = (videoId, captions, requested) -> {
        mReady.add(videoId);
        mRequested.add(requested);
    };

    @Before
    public void setUp() {
        mFollower = new UtubotCaptionsFollower(mScheduler, this::fetch, mScheduler::now);
    }

    @Test
    public void captionsReadyAtTheStart_areHandedOverAsNotRequested() {
        mAnswers.add(captions("ready"));

        mFollower.follow(VIDEO, mListener);

        assertEquals(Collections.singletonList(VIDEO), mReady);
        assertEquals(Collections.singletonList(false), mRequested);
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void noJob_asksOnceAndStops() {
        mAnswers.add(captions("none"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(UtubotCaptionsFollower.MAX_FOLLOW_MS);

        assertEquals(1, mFetched.size());
        assertTrue(mReady.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aFailedJob_isNotWaitedFor() {
        mAnswers.add(captions("failed"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS * 3);

        assertEquals(1, mFetched.size());
        assertTrue(mReady.isEmpty());
    }

    @Test
    public void aJobThatFinishesWhileTheVideoPlays_isHandedOverAsRequested() {
        mAnswers.add(captions("running"));
        mAnswers.add(captions("running"));
        mAnswers.add(captions("ready"));

        mFollower.follow(VIDEO, mListener);
        assertEquals(1, mFetched.size());
        assertTrue(mReady.isEmpty());

        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS - 1);
        assertEquals(1, mFetched.size());

        mScheduler.advance(1);
        assertEquals(2, mFetched.size());
        assertTrue(mReady.isEmpty());

        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS);
        assertEquals(3, mFetched.size());
        assertEquals(Collections.singletonList(VIDEO), mReady);
        assertEquals(Collections.singletonList(true), mRequested);

        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS * 5);
        assertEquals(3, mFetched.size());
    }

    @Test
    public void aQueuedJob_isFollowedLikeARunningOne() {
        mAnswers.add(captions("queued"));
        mAnswers.add(captions("ready"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS);

        assertEquals(Collections.singletonList(true), mRequested);
    }

    @Test
    public void theUserAsksWhileTheVideoPlays_theJobIsFollowed() {
        mAnswers.add(captions("none"));
        mFollower.follow(VIDEO, mListener);
        assertEquals(0, mScheduler.pending());

        mFollower.requested(VIDEO, "queued");
        assertEquals(1, mScheduler.pending());

        mAnswers.add(captions("running"));
        mAnswers.add(captions("ready"));
        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS * 2);

        assertEquals(Collections.singletonList(true), mRequested);
    }

    @Test
    public void theUserAsksForCaptionsThatAreReady_theyAreFetchedAtOnce() {
        mAnswers.add(captions("none"));
        mFollower.follow(VIDEO, mListener);

        mAnswers.add(captions("ready"));
        mFollower.requested(VIDEO, "ready");

        assertEquals(Collections.singletonList(true), mRequested);
    }

    @Test
    public void aRequestForAnotherVideo_isNotFollowed() {
        mAnswers.add(captions("none"));
        mFollower.follow(VIDEO, mListener);

        mFollower.requested(OTHER_VIDEO, "queued");

        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aRequestThatFailed_isNotFollowed() {
        mAnswers.add(captions("none"));
        mFollower.follow(VIDEO, mListener);

        mFollower.requested(VIDEO, "failed");

        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void stopping_dropsThePollAndALateAnswer() {
        mAnswers.add(captions("running"));
        mFollower.follow(VIDEO, mListener);
        assertEquals(1, mScheduler.pending());

        mFollower.stop(mListener);

        assertEquals(0, mScheduler.pending());
        mAnswers.add(captions("ready"));
        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS * 3);
        assertEquals(1, mFetched.size());
        assertTrue(mReady.isEmpty());
    }

    @Test
    public void aListenerThatIsNotFollowingAnymore_doesNotStopTheNewOne() {
        UtubotCaptionsFollower.Listener older = (videoId, captions, requested) -> { };
        mAnswers.add(captions("running"));
        mFollower.follow(VIDEO, older);
        mAnswers.add(captions("running"));
        mFollower.follow(OTHER_VIDEO, mListener);

        mFollower.stop(older);

        assertEquals(1, mScheduler.pending());
    }

    @Test
    public void anotherVideo_dropsTheAnswerStillOnItsWay() {
        List<UtubotCaptionsFollower.Callback> pending = new ArrayList<>();
        mFollower = new UtubotCaptionsFollower(mScheduler, (videoId, callback) -> pending.add(callback), mScheduler::now);

        mFollower.follow(VIDEO, mListener);
        mFollower.follow(OTHER_VIDEO, mListener);
        pending.get(0).onResult(captions("ready"));

        assertTrue(mReady.isEmpty());

        pending.get(1).onResult(captions("ready"));
        assertEquals(Collections.singletonList(OTHER_VIDEO), mReady);
    }

    @Test
    public void theSameVideoAgain_changesNothing() {
        mAnswers.add(captions("running"));
        mFollower.follow(VIDEO, mListener);

        mFollower.follow(VIDEO, mListener);

        assertEquals(1, mFetched.size());
        assertEquals(1, mScheduler.pending());
    }

    @Test
    public void withoutAJob_anErrorEndsIt() {
        mAnswers.add(new IOException("offline"));

        mFollower.follow(VIDEO, mListener);

        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void whileAJobRuns_anErrorIsTriedAgain() {
        mAnswers.add(captions("running"));
        mAnswers.add(new IOException("offline"));
        mAnswers.add(captions("ready"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS * 2);

        assertEquals(Collections.singletonList(true), mRequested);
    }

    @Test
    public void whileAJobRuns_repeatedErrorsGiveUp() {
        mAnswers.add(captions("running"));

        mFollower.follow(VIDEO, mListener);

        for (int i = 0; i < UtubotCaptionsFollower.MAX_ERRORS + 2; i++) {
            mAnswers.add(new IOException("offline"));
        }

        mScheduler.advance(UtubotCaptionsFollower.POLL_INTERVAL_MS * (UtubotCaptionsFollower.MAX_ERRORS + 2));

        assertEquals(1 + UtubotCaptionsFollower.MAX_ERRORS, mFetched.size());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aJobThatNeverFinishes_isGivenUpOn() {
        for (int i = 0; i < 1000; i++) {
            mAnswers.add(captions("running"));
        }

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(UtubotCaptionsFollower.MAX_FOLLOW_MS + UtubotCaptionsFollower.POLL_INTERVAL_MS);

        assertEquals(0, mScheduler.pending());
        assertFalse(mFetched.size() > UtubotCaptionsFollower.MAX_FOLLOW_MS / UtubotCaptionsFollower.POLL_INTERVAL_MS + 1);
        assertTrue(mReady.isEmpty());
    }

    private void fetch(String videoId, UtubotCaptionsFollower.Callback callback) {
        mFetched.add(videoId);
        Object answer = mAnswers.remove();

        if (answer instanceof Throwable) {
            callback.onError((Throwable) answer);
        } else {
            callback.onResult((Captions) answer);
        }
    }

    private static Captions captions(String status) {
        Captions captions = new Captions();
        captions.status = status;

        if ("ready".equals(status)) {
            CaptionTrack track = new CaptionTrack();
            track.lang = "tr";
            track.label = "Turkish (u·tubot)";
            track.url = "/v1/videos/" + VIDEO + "/captions/tr.vtt";
            captions.tracks = Collections.singletonList(track);
        }

        return captions;
    }
}
