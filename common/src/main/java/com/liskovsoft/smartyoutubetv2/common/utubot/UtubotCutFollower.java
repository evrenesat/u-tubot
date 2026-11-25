package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;

import java.util.ArrayList;
import java.util.List;

/**
 * Follows the director's cuts of the video that plays. It asks the backend once where the video's cuts stand and, while a request for
 * it is waiting or building, long-polls that request until the cut is ready, so one built on the phone reaches the player while the
 * video plays. Everything runs on the thread the scheduler and the fetcher call back on (the main thread).
 */
public final class UtubotCutFollower {
    /** A build may wait for its transcript for a long time; beyond this the request is not followed any more */
    public static final long MAX_FOLLOW_MS = 30 * 60 * 1000L;
    public static final int MAX_ERRORS = 5;
    /** How long one long poll of the request may hold the answer (the backend's cap is 20 s) */
    public static final int REQUEST_WAIT_MS = 10_000;

    /**
     * Asks the backend off the main thread and answers on the main thread
     */
    public interface Fetcher {
        void fetchCuts(String videoId, CutsCallback callback);

        void fetchRequest(String requestId, int waitMs, RequestCallback callback);
    }

    public interface CutsCallback {
        void onResult(CutList cuts);

        void onError(Throwable error);
    }

    public interface RequestCallback {
        void onResult(CutRequest request);

        void onError(Throwable error);
    }

    public interface Listener {
        /**
         * @param requested the cut became ready while this TV waited for the request it created, as opposed to a cut that was already
         *                  there when the video opened
         */
        void onCutReady(String videoId, Cut cut, boolean requested);

        /**
         * The video opens with the cut the viewer chose (or the preset used last): it is applied without an offer.
         */
        default void onCutChosen(String videoId, Cut cut) {
            onCutReady(videoId, cut, true);
        }

        /**
         * No cut is chosen for the video and the last-used preset has none ready: the ready cuts are offered, none applied.
         */
        default void onCutsReady(String videoId, List<Cut> cuts) {
            if (!cuts.isEmpty()) {
                onCutReady(videoId, cuts.get(0), false);
            }
        }
    }

    public interface Clock {
        long nowMs();
    }

    private final UtubotScheduler mScheduler;
    private final Fetcher mFetcher;
    private final Clock mClock;
    private final Runnable mPoll = this::fetch;
    @Nullable
    private String mVideoId;
    @Nullable
    private String mRequestId;
    @Nullable
    private Listener mListener;
    private boolean mRequested;
    private boolean mChosen;
    private long mStartedMs;
    private int mErrors;
    private int mGeneration;

    public UtubotCutFollower(UtubotScheduler scheduler, Fetcher fetcher, Clock clock) {
        mScheduler = scheduler;
        mFetcher = fetcher;
        mClock = clock;
    }

    /**
     * The video starts: finds out where its cuts stand. The same video again changes nothing.
     */
    public void follow(String videoId, Listener listener) {
        if (videoId.equals(mVideoId) && listener == mListener) {
            return;
        }

        stop();
        mVideoId = videoId;
        mListener = listener;
        mStartedMs = mClock.nowMs();
        fetch();
    }

    /**
     * A request was created for the video that plays (the menu asked for a cut), which answered with this id. Only the video that
     * plays is followed.
     */
    public void requested(String videoId, @Nullable String requestId, @Nullable String state) {
        if (!videoId.equals(mVideoId) || requestId == null) {
            return;
        }

        if (requestId.equals(mRequestId) && mRequestId != null) {
            return; // already followed
        }

        mGeneration++;
        mRequestId = requestId;
        mRequested = true;
        mChosen = false;
        mErrors = 0;
        mStartedMs = mClock.nowMs();

        if (isPending(state)) {
            scheduleNext();
        } else {
            fetch();
        }
    }

    /**
     * The video is gone. Only the listener that follows now stops it, not an older one that is released late.
     */
    public void stop(Listener listener) {
        if (listener == mListener) {
            stop();
        }
    }

    public void stop() {
        stopPolling();
        mVideoId = null;
        mRequestId = null;
        mListener = null;
    }

    /**
     * Nothing more to wait for, but the video still plays: the user may yet ask for a cut
     */
    private void stopPolling() {
        mScheduler.remove(mPoll);
        mGeneration++;
        mRequestId = null;
        mRequested = false;
        mChosen = false;
        mErrors = 0;
    }

    private void fetch() {
        if (mRequestId != null) {
            fetchRequest();
        } else {
            fetchCuts();
        }
    }

    private void fetchCuts() {
        String videoId = mVideoId;

        if (videoId == null) {
            return;
        }

        int generation = ++mGeneration;

        mFetcher.fetchCuts(videoId, new CutsCallback() {
            @Override
            public void onResult(CutList cuts) {
                if (generation == mGeneration) {
                    onCuts(videoId, cuts);
                }
            }

            @Override
            public void onError(Throwable error) {
                if (generation == mGeneration) {
                    onFailure();
                }
            }
        });
    }

    private void onCuts(String videoId, CutList cuts) {
        mErrors = 0;

        if (cuts == null || !cuts.configured) {
            stopPolling();
            return;
        }

        Listener listener = mListener;

        if (cuts.selection != null && cuts.selection.cut != null && !cuts.selection.off) {
            // The chosen cut, or the preset used last: applied, never replaced by the first ready one
            if (listener != null) {
                listener.onCutChosen(videoId, cuts.selection.cut);
            }
        } else if (cuts.selection == null && listener != null) {
            // Nothing was chosen and the last preset has no ready cut: offer what is ready, apply none
            List<Cut> ready = readyCuts(cuts);

            if (!ready.isEmpty()) {
                listener.onCutsReady(videoId, ready);
            }
        }

        if (cuts.selection != null && cuts.selection.requestId != null && !cuts.selection.off
                && isPending(cuts.selection.state)) {
            // The viewer chose a request that is still building: follow that one, not a preset in the list, and
            // apply it as the chosen cut when it becomes ready
            mRequestId = cuts.selection.requestId;
            mRequested = false;
            mChosen = true;
            scheduleNext();
            return;
        }

        if (cuts.selection == null) {
            for (CutPreset preset : cuts.presets) {
                if (isPending(preset.state) && preset.requestId != null) {
                    mRequestId = preset.requestId;
                    mRequested = false;
                    mChosen = false;
                    scheduleNext();
                    return;
                }
            }
        }

        stopPolling();
    }

    private static List<Cut> readyCuts(CutList cuts) {
        List<Cut> ready = new ArrayList<>();

        for (CutPreset preset : cuts.presets) {
            if (preset.isReady()) {
                ready.add(preset.cut);
            }
        }

        return ready;
    }

    private void fetchRequest() {
        String requestId = mRequestId;
        String videoId = mVideoId;

        if (requestId == null) {
            return;
        }

        int generation = ++mGeneration;

        mFetcher.fetchRequest(requestId, REQUEST_WAIT_MS, new RequestCallback() {
            @Override
            public void onResult(CutRequest request) {
                if (generation == mGeneration) {
                    onRequest(videoId, request);
                }
            }

            @Override
            public void onError(Throwable error) {
                if (generation == mGeneration) {
                    onFailure();
                }
            }
        });
    }

    private void onRequest(String videoId, CutRequest request) {
        mErrors = 0;

        if (request == null || !request.id.equals(mRequestId)) {
            stopPolling();
            return;
        }

        if (request.isReady()) {
            // The video still plays and a next request for it must be followed, so only the poll ends; the listener and the video stay
            Listener listener = mListener;
            boolean requested = mRequested;
            boolean chosen = mChosen;
            stopPolling();

            if (listener != null) {
                if (chosen) {
                    // The request was the viewer's choice for the video: it applies, no Apply prompt
                    listener.onCutChosen(videoId, request.cut);
                } else {
                    listener.onCutReady(videoId, request.cut, requested);
                }
            }
        } else if (request.isDone()) {
            // failed or dismissed: the phone queue says why; the picker shows the state next time it opens
            stopPolling();
        } else {
            scheduleNext();
        }
    }

    private void onFailure() {
        // A request the user asked for is waited for through a few errors; a plain check is not
        if (!mRequested || ++mErrors >= MAX_ERRORS) {
            stopPolling();
            return;
        }

        mScheduler.remove(mPoll);

        if (mClock.nowMs() - mStartedMs > MAX_FOLLOW_MS) {
            stopPolling();
            return;
        }

        mScheduler.postDelayed(mPoll, retryDelayMs());
    }

    /**
     * A moment between the retries of a long poll: 1 s, 2 s, then 5 s, so a network drop does not burn the error budget at once
     */
    private long retryDelayMs() {
        switch (mErrors) {
            case 1:
                return 1_000;
            case 2:
                return 2_000;
            default:
                return 5_000;
        }
    }

    /**
     * A long poll comes back as soon as there is news, so the next one goes out at once; the cap ends a follow that never answers
     */
    private void scheduleNext() {
        mScheduler.remove(mPoll);

        if (mClock.nowMs() - mStartedMs > MAX_FOLLOW_MS) {
            stopPolling();
            return;
        }

        mScheduler.postDelayed(mPoll, 0);
    }

    private static boolean isPending(@Nullable String state) {
        return UtubotModels.CutState.WAITING.equals(state) || UtubotModels.CutState.BUILDING.equals(state);
    }
}