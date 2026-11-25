package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;

import org.junit.Before;
import org.junit.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * The app-wide follower of ordered cuts (issue 96): a ready cut is reported, a failed one with its reason, a cut that became ready
 * while the app was closed is not, and an old one stops being followed.
 */
public class UtubotCutWatcherTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String REQUEST = "cut1";
    private static final long DRAIN_MS = 60_000;

    private final FakeScheduler mScheduler = new FakeScheduler();
    private final FakeCutWaitlistStore mStore = new FakeCutWaitlistStore();
    private final Queue<Object> mAnswers = new ConcurrentLinkedQueue<>();
    private final List<String> mFetched = new ArrayList<>();
    private final List<Integer> mWaits = new ArrayList<>();
    private final List<String> mReady = new ArrayList<>();
    private final List<String> mFailed = new ArrayList<>();
    private final List<String> mErrors = new ArrayList<>();
    private UtubotCutWaitlist mWaitlist;
    private UtubotCutWatcher mWatcher;

    @Before
    public void setUp() {
        mWaitlist = new UtubotCutWaitlist(mStore);
        mWatcher = new UtubotCutWatcher(mScheduler, (requestId, waitMs, callback) -> {
            mFetched.add(requestId);
            mWaits.add(waitMs);
            Object answer = mAnswers.poll();

            if (answer instanceof Throwable) {
                callback.onError((Throwable) answer);
            } else if (answer == null) {
                callback.onError(new IOException("no answer queued"));
            } else {
                callback.onResult((CutRequest) answer);
            }
        }, mScheduler::now, mWaitlist, new UtubotCutWatcher.Listener() {
            @Override
            public void onCutReady(Entry entry, Cut cut) {
                mReady.add(entry.requestId);
            }

            @Override
            public void onCutFailed(Entry entry, String error) {
                mFailed.add(entry.requestId);
                mErrors.add(error);
            }
        });
    }

    @Test
    public void aCutOrderedWhileTheAppIsOpen_isReportedWhenReady() {
        mWatcher.watch(entry(0));
        mAnswers.add(request("building"));
        mAnswers.add(request("ready"));

        mScheduler.advance(DRAIN_MS);

        assertEquals(Collections.singletonList(REQUEST), mReady);
        assertEquals(Arrays.asList(UtubotCutWatcher.REQUEST_WAIT_MS, UtubotCutWatcher.REQUEST_WAIT_MS), mWaits);
        assertTrue(mWaitlist.entries().isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void aCutThatBecameReadyWhileTheAppWasClosed_isNotAnnounced() {
        mWaitlist.add(entry(0));
        mAnswers.add(request("ready"));

        mWatcher.start();
        mScheduler.advance(DRAIN_MS);

        assertTrue(mReady.isEmpty());
        assertEquals(Collections.singletonList(UtubotCutWatcher.STATUS_WAIT_MS), mWaits);
        assertTrue(mWaitlist.entries().isEmpty());
    }

    @Test
    public void aCutStillBuildingAtStartup_isFollowedToReady() {
        mWaitlist.add(entry(0));
        mAnswers.add(request("building"));
        mAnswers.add(request("ready"));

        mWatcher.start();
        mScheduler.advance(DRAIN_MS);

        assertEquals(Collections.singletonList(REQUEST), mReady);
        assertEquals(Arrays.asList(UtubotCutWatcher.STATUS_WAIT_MS, UtubotCutWatcher.REQUEST_WAIT_MS), mWaits);
        assertTrue(mWaitlist.entries().isEmpty());
    }

    @Test
    public void aFailureWhileTheAppIsOpen_reportsTheReason() {
        mWatcher.watch(entry(0));
        mAnswers.add(request("failed", "The model kept only 40 s of the 300 s this cut aims for"));

        mScheduler.advance(DRAIN_MS);

        assertEquals(Collections.singletonList(REQUEST), mFailed);
        assertEquals(Collections.singletonList("The model kept only 40 s of the 300 s this cut aims for"), mErrors);
        assertTrue(mWaitlist.entries().isEmpty());
    }

    @Test
    public void aFailureWhileTheAppWasClosed_reportsItAtTheNextStart() {
        mWaitlist.add(entry(0));
        mAnswers.add(request("failed", "nothing to cut"));

        mWatcher.start();
        mScheduler.advance(DRAIN_MS);

        assertEquals(Collections.singletonList("nothing to cut"), mErrors);
        assertTrue(mWaitlist.entries().isEmpty());
    }

    @Test
    public void aDismissedRequest_isDroppedSilently() {
        mWatcher.watch(entry(0));
        mAnswers.add(request("dismissed"));

        mScheduler.advance(DRAIN_MS);

        assertTrue(mReady.isEmpty());
        assertTrue(mFailed.isEmpty());
        assertTrue(mWaitlist.entries().isEmpty());
    }

    @Test
    public void anOldRequest_stopsBeingFollowed() {
        mWaitlist.add(entry(-UtubotCutWaitlist.MAX_AGE_MS - 1));
        mAnswers.add(request("building"));

        mWatcher.start();
        mScheduler.advance(DRAIN_MS);

        assertTrue(mReady.isEmpty());
        assertEquals(1, mFetched.size());
        assertTrue(mWaitlist.entries().isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void errorsAreRetriedThenTheRequestIsFollowed() {
        mWatcher.watch(entry(0));
        mAnswers.add(new IOException("down"));
        mAnswers.add(new IOException("down"));
        mAnswers.add(request("ready"));

        mScheduler.advance(DRAIN_MS);

        assertEquals(Collections.singletonList(REQUEST), mReady);
        assertEquals(3, mFetched.size());
    }

    @Test
    public void tooManyErrors_giveUp() {
        mWatcher.watch(entry(0));

        for (int i = 0; i < UtubotCutWatcher.MAX_ERRORS; i++) {
            mAnswers.add(new IOException("down"));
        }

        mScheduler.advance(DRAIN_MS);

        assertTrue(mReady.isEmpty());
        assertTrue(mFailed.isEmpty());
        assertTrue(mWaitlist.entries().isEmpty());
        assertEquals(UtubotCutWatcher.MAX_ERRORS, mFetched.size());
    }

    @Test
    public void eachOrderedCutIsFollowed() {
        mWatcher.watch(entry("cut1", 0));
        mWatcher.watch(entry("cut2", 0));
        mAnswers.add(requestFor("cut1", "ready"));
        mAnswers.add(requestFor("cut2", "ready"));

        mScheduler.advance(DRAIN_MS);

        assertEquals(Arrays.asList("cut1", "cut2"), mReady);
    }

    @Test
    public void stoppingTheWatcher_stopsThePollsButKeepsTheOrdersForTheNextStart() {
        mWaitlist.add(entry(0));
        mWatcher.start();
        assertEquals(1, mScheduler.pending());

        mWatcher.stop();

        assertEquals(0, mScheduler.pending());
        assertEquals(1, mWaitlist.entries().size());
    }

    private static Entry entry(long orderedAtMs) {
        return entry(REQUEST, orderedAtMs);
    }

    private static Entry entry(String requestId, long orderedAtMs) {
        return new Entry(requestId, VIDEO, "The demo", orderedAtMs);
    }

    private static CutRequest request(String state) {
        return requestFor(REQUEST, state, null);
    }

    private static CutRequest request(String state, String error) {
        return requestFor(REQUEST, state, error);
    }

    private static CutRequest requestFor(String id, String state) {
        return requestFor(id, state, null);
    }

    private static CutRequest requestFor(String id, String state, String error) {
        CutRequest request = new CutRequest();
        request.id = id;
        request.videoId = VIDEO;
        request.state = state;
        request.error = error;

        if (UtubotModels.CutState.READY.equals(state)) {
            Cut cut = new Cut();
            cut.videoId = VIDEO;
            cut.label = "No filler";
            cut.keptMs = 192_000;
            request.cut = cut;
        }

        return request;
    }
}
