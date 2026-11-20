package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;

import org.junit.Before;
import org.junit.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class UtubotCutFollowerTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String OTHER_VIDEO = "abcdefghijk";
    private static final String REQUEST = "cut1";
    /** The polls of a request go out one after another; this is enough for the whole chain to drain */
    private static final long DRAIN_MS = 60_000;

    private final FakeScheduler mScheduler = new FakeScheduler();
    private final Queue<Object> mCutsAnswers = new ConcurrentLinkedQueue<>();
    private final Queue<Object> mRequestAnswers = new ConcurrentLinkedQueue<>();
    private final List<String> mFetchedCuts = new ArrayList<>();
    private final List<String> mFetchedRequests = new ArrayList<>();
    private final List<String> mReady = new ArrayList<>();
    private final List<Boolean> mRequested = new ArrayList<>();
    private UtubotCutFollower mFollower;
    private final UtubotCutFollower.Listener mListener = (videoId, cut, requested) -> {
        mReady.add(videoId);
        mRequested.add(requested);
    };
    private final UtubotCutFollower.Listener mStranger = (videoId, cut, requested) -> { };

    @Before
    public void setUp() {
        mFollower = new UtubotCutFollower(mScheduler, new UtubotCutFollower.Fetcher() {
            @Override
            public void fetchCuts(String videoId, UtubotCutFollower.CutsCallback callback) {
                mFetchedCuts.add(videoId);
                Object answer = mCutsAnswers.poll();

                if (answer instanceof Throwable) {
                    callback.onError((Throwable) answer);
                } else {
                    callback.onResult((CutList) answer);
                }
            }

            @Override
            public void fetchRequest(String requestId, int waitMs, UtubotCutFollower.RequestCallback callback) {
                mFetchedRequests.add(requestId);
                Object answer = mRequestAnswers.poll();

                if (answer instanceof Throwable) {
                    callback.onError((Throwable) answer);
                } else {
                    callback.onResult((CutRequest) answer);
                }
            }
        }, mScheduler::now);
    }

    @Test
    public void aReadyCutAtTheStart_isAnnouncedAsNotRequested() {
        mCutsAnswers.add(cuts("cut-no-filler", "ready"));

        mFollower.follow(VIDEO, mListener);

        assertEquals(Collections.singletonList(VIDEO), mReady);
        assertEquals(Collections.singletonList(false), mRequested);
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void noCuts_asksOnceAndStops() {
        mCutsAnswers.add(cutsEmpty());

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(DRAIN_MS);

        assertEquals(1, mFetchedCuts.size());
        assertTrue(mReady.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void anUnconfiguredBackend_isNotFollowed() {
        CutList cuts = cutsEmpty();
        cuts.configured = false;
        mCutsAnswers.add(cuts);

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(DRAIN_MS);

        assertEquals(1, mFetchedCuts.size());
        assertTrue(mReady.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aBuildingRequest_isLongPolledUntilReady() {
        mCutsAnswers.add(cuts("cut-no-filler", "building"));
        mRequestAnswers.add(request("building"));
        mRequestAnswers.add(request("ready"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(DRAIN_MS);

        assertEquals(1, mFetchedCuts.size());
        assertEquals(2, mFetchedRequests.size());
        assertEquals(Collections.singletonList(VIDEO), mReady);
        assertEquals(Collections.singletonList(false), mRequested);
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aRequestTheTvAskedFor_isAnnouncedAsRequested() {
        mCutsAnswers.add(cutsEmpty());
        mFollower.follow(VIDEO, mListener);
        mFollower.requested(VIDEO, REQUEST, "building");
        mRequestAnswers.add(request("ready"));

        mScheduler.advance(DRAIN_MS);

        assertEquals(Collections.singletonList(VIDEO), mReady);
        assertEquals(Collections.singletonList(true), mRequested);
    }

    @Test
    public void aRequestOfAnotherVideo_isNotFollowed() {
        mCutsAnswers.add(cutsEmpty());
        mFollower.follow(VIDEO, mListener);

        mFollower.requested(OTHER_VIDEO, REQUEST, "building");
        mScheduler.advance(DRAIN_MS);

        assertTrue(mFetchedRequests.isEmpty());
    }

    @Test
    public void aFailedRequest_stopsTheFollow() {
        mCutsAnswers.add(cuts("cut-no-filler", "building"));
        mRequestAnswers.add(request("failed"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(DRAIN_MS);

        assertTrue(mReady.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aDismissedRequest_stopsTheFollow() {
        mCutsAnswers.add(cuts("cut-no-filler", "waiting"));
        mRequestAnswers.add(request("dismissed"));

        mFollower.follow(VIDEO, mListener);
        mScheduler.advance(DRAIN_MS);

        assertTrue(mReady.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void errorsOfAnAskedRequest_areRetriedUntilItAnswers() {
        mCutsAnswers.add(cutsEmpty());
        mFollower.follow(VIDEO, mListener);
        mFollower.requested(VIDEO, REQUEST, "building");

        for (int i = 0; i < UtubotCutFollower.MAX_ERRORS - 1; i++) {
            mRequestAnswers.add(new IOException("down"));
        }
        mRequestAnswers.add(request("ready"));

        mScheduler.advance(DRAIN_MS);

        assertEquals(UtubotCutFollower.MAX_ERRORS, mFetchedRequests.size());
        assertEquals(Collections.singletonList(VIDEO), mReady);
    }

    @Test
    public void tooManyErrors_giveUp() {
        mCutsAnswers.add(cutsEmpty());
        mFollower.follow(VIDEO, mListener);
        mFollower.requested(VIDEO, REQUEST, "building");

        for (int i = 0; i < UtubotCutFollower.MAX_ERRORS; i++) {
            mRequestAnswers.add(new IOException("down"));
        }

        mScheduler.advance(DRAIN_MS);

        assertEquals(UtubotCutFollower.MAX_ERRORS, mFetchedRequests.size());
        assertTrue(mReady.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aFollowThatNeverAnswers_endsAtTheCap() {
        mCutsAnswers.add(cuts("cut-no-filler", "building"));

        mFollower.follow(VIDEO, mListener);

        long polled = 0;
        while (mScheduler.pending() > 0 && polled <= UtubotCutFollower.MAX_FOLLOW_MS) {
            mRequestAnswers.add(request("building"));
            mScheduler.advance(UtubotCutFollower.REQUEST_WAIT_MS + 1);
            polled += UtubotCutFollower.REQUEST_WAIT_MS + 1;
        }

        assertTrue(polled <= UtubotCutFollower.MAX_FOLLOW_MS + 2 * UtubotCutFollower.REQUEST_WAIT_MS);
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void theStopOfAStranger_doesNotEndTheFollow() {
        mCutsAnswers.add(cuts("cut-no-filler", "building"));
        mFollower.follow(VIDEO, mListener);

        mFollower.stop(mStranger);
        mRequestAnswers.add(request("ready"));
        mScheduler.advance(DRAIN_MS);

        assertEquals(1, mFetchedCuts.size());
        assertEquals(1, mFetchedRequests.size());
        assertEquals(Collections.singletonList(VIDEO), mReady);
    }

    @Test
    public void theStopOfItsOwnListener_endsTheFollow() {
        mCutsAnswers.add(cuts("cut-no-filler", "building"));
        mFollower.follow(VIDEO, mListener);

        mFollower.stop(mListener);
        mRequestAnswers.add(request("ready"));
        mScheduler.advance(DRAIN_MS);

        assertEquals(1, mFetchedCuts.size());
        assertTrue(mFetchedRequests.isEmpty());
        assertTrue(mReady.isEmpty());
    }

    private static CutList cutsEmpty() {
        CutList cuts = new CutList();
        cuts.configured = true;
        cuts.presets = Collections.emptyList();
        return cuts;
    }

    private static CutList cuts(String presetId, String state) {
        CutList cuts = cutsEmpty();
        CutPreset preset = new CutPreset();
        preset.id = presetId;
        preset.label = "No filler";
        preset.state = state;
        preset.requestId = REQUEST;

        if (UtubotModels.CutState.READY.equals(state)) {
            preset.cut = cut();
        }

        cuts.presets = Collections.singletonList(preset);
        return cuts;
    }

    private static CutRequest request(String state) {
        CutRequest request = new CutRequest();
        request.id = REQUEST;
        request.videoId = VIDEO;
        request.state = state;

        if (UtubotModels.CutState.READY.equals(state)) {
            request.cut = cut();
        }

        return request;
    }

    private static Cut cut() {
        Cut cut = new Cut();
        cut.videoId = VIDEO;
        cut.durationMs = 240_000;
        cut.keptMs = 150_000;
        cut.label = "No filler";
        cut.skipRangesMs = Collections.singletonList(new long[]{60_000, 108_000});
        return cut;
    }
}