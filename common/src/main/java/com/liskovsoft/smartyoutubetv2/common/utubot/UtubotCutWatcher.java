package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutState;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Follows the cut requests this TV ordered wherever the viewer is (issue 96). Each request is asked through the cut-request status
 * endpoint while it waits or builds; a ready one is reported once and leaves the list, a failed one reports its reason, and one that is
 * old stops being followed. On the first check after a start the status is read without waiting: a cut that became ready while the app
 * was closed is not announced, while its failure is.
 */
public final class UtubotCutWatcher {
    /** How long one long poll of a request may hold the answer (the backend's cap is 20 s) */
    public static final int REQUEST_WAIT_MS = 10_000;
    /** The first check after a start does not wait: it learns the state the request had while the app was closed */
    public static final int STATUS_WAIT_MS = 1;
    private static final long MAX_RETRY_MS = 30_000;

    public interface Fetcher {
        void fetchRequest(String requestId, int waitMs, Callback callback);
    }

    public interface Callback {
        void onResult(CutRequest request);

        void onError(Throwable error);
    }

    public interface Clock {
        long nowMs();
    }

    public interface Listener {
        void onCutReady(Entry entry, Cut cut);

        void onCutFailed(Entry entry, @Nullable String error);
    }

    private static final class Watch {
        final Entry entry;
        boolean catchUp;
        boolean done;
        int generation;
        int errors;
        Runnable poll;

        Watch(Entry entry, boolean catchUp) {
            this.entry = entry;
            this.catchUp = catchUp;
        }
    }

    private final UtubotScheduler mScheduler;
    private final Fetcher mFetcher;
    private final Clock mClock;
    private final UtubotCutWaitlist mWaitlist;
    private final Listener mListener;
    private final Map<String, Watch> mWatches = new LinkedHashMap<>();

    public UtubotCutWatcher(UtubotScheduler scheduler, Fetcher fetcher, Clock clock, UtubotCutWaitlist waitlist, Listener listener) {
        mScheduler = scheduler;
        mFetcher = fetcher;
        mClock = clock;
        mWaitlist = waitlist;
        mListener = listener;
    }

    /**
     * The app starts: every request kept on the device is checked once without waiting.
     */
    public void start() {
        for (Entry entry : mWaitlist.entries()) {
            watch(entry, true);
        }
    }

    /**
     * A cut this TV just ordered: follow it until it is ready, failed or old.
     */
    public void watch(Entry entry) {
        watch(entry, false);
    }

    public void stop() {
        for (Watch watch : new ArrayList<>(mWatches.values())) {
            cancel(watch);
        }

        mWatches.clear();
    }

    private void watch(Entry entry, boolean catchUp) {
        if (entry == null || entry.requestId == null || mWatches.containsKey(entry.requestId)) {
            return;
        }

        Watch watch = new Watch(entry, catchUp);
        watch.poll = () -> fetch(watch);
        mWatches.put(entry.requestId, watch);
        schedule(watch, 0);
    }

    private void fetch(Watch watch) {
        if (watch.done || mWatches.get(watch.entry.requestId) != watch) {
            return;
        }

        int generation = ++watch.generation;
        int waitMs = watch.catchUp ? STATUS_WAIT_MS : REQUEST_WAIT_MS;

        mFetcher.fetchRequest(watch.entry.requestId, waitMs, new Callback() {
            @Override
            public void onResult(CutRequest request) {
                if (generation != watch.generation || watch.done) {
                    return;
                }

                onRequest(watch, request);
            }

            @Override
            public void onError(Throwable error) {
                if (generation != watch.generation || watch.done) {
                    return;
                }

                onFailure(watch);
            }
        });
    }

    private void onRequest(Watch watch, @Nullable CutRequest request) {
        watch.errors = 0;

        if (request == null || !watch.entry.requestId.equals(request.id)) {
            finish(watch);
            return;
        }

        if (request.isReady()) {
            boolean catchUp = watch.catchUp;
            Cut cut = request.cut;
            finish(watch);

            if (!catchUp && cut != null) {
                mListener.onCutReady(watch.entry, cut);
            }

            return;
        }

        if (request.isDone()) {
            boolean failed = CutState.FAILED.equals(request.state);
            String error = request.error;
            finish(watch);

            if (failed) {
                mListener.onCutFailed(watch.entry, error);
            }

            return;
        }

        watch.catchUp = false;

        if (isOld(watch.entry)) {
            finish(watch);
            return;
        }

        // A long poll comes back as soon as there is news, so the next one goes out at once
        schedule(watch, 0);
    }

    private void onFailure(Watch watch) {
        // A few network errors do not lose the order: it is kept until the cut is ready, failed or old
        if (isOld(watch.entry)) {
            finish(watch);
            return;
        }

        schedule(watch, retryDelayMs(++watch.errors));
    }

    private void schedule(Watch watch, long delayMs) {
        mScheduler.remove(watch.poll);
        mScheduler.postDelayed(watch.poll, delayMs);
    }

    private void finish(Watch watch) {
        watch.done = true;
        mScheduler.remove(watch.poll);
        mWatches.remove(watch.entry.requestId);
        mWaitlist.remove(watch.entry.requestId);
    }

    private void cancel(Watch watch) {
        watch.done = true;
        watch.generation++;
        mScheduler.remove(watch.poll);
    }

    private boolean isOld(Entry entry) {
        return mClock.nowMs() - entry.orderedAtMs > UtubotCutWaitlist.MAX_AGE_MS;
    }

    /**
     * A moment between the retries of a long poll: 1 s, 2 s, 5 s, 10 s, then at most 30 s. A network drop must neither hammer the
     * backend nor lose an order that is still being built.
     */
    private static long retryDelayMs(int errors) {
        switch (errors) {
            case 1:
                return 1_000;
            case 2:
                return 2_000;
            case 3:
                return 5_000;
            case 4:
                return 10_000;
            default:
                return MAX_RETRY_MS;
        }
    }

    /** Where a request stands: still waiting, building or waiting for its transcript */
    public static boolean isPending(@Nullable String state) {
        return CutState.WAITING.equals(state) || CutState.BUILDING.equals(state) || CutState.NEEDS_TRANSCRIPT.equals(state);
    }
}
