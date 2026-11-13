package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;

/**
 * Follows the HQ captions of the video that plays. It asks the backend once when the video starts and, while the answer is "queued" or
 * "running" (a job the user asked for, here or on another device), asks again until the captions are ready, so a job that finishes
 * while the video plays reaches the player. Everything runs on the thread the scheduler and the fetcher call back on (the main thread).
 */
public final class UtubotCaptionsFollower {
    public static final long POLL_INTERVAL_MS = 10_000;
    /** A job that takes longer than this is not waited for */
    public static final long MAX_FOLLOW_MS = 2 * 60 * 60 * 1000L;
    public static final int MAX_ERRORS = 5;

    /**
     * Asks the backend for the captions of a video, off the main thread, and answers on the main thread
     */
    public interface Fetcher {
        void fetch(String videoId, Callback callback);
    }

    public interface Callback {
        void onResult(Captions captions);

        void onError(Throwable error);
    }

    public interface Listener {
        /**
         * @param requested the captions were not ready when the video started or the user asked for them (a job finished, or the user
         *                  wants them now), as opposed to captions that were there and only came late
         */
        void onCaptionsReady(String videoId, Captions captions, boolean requested);
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
    private Listener mListener;
    private boolean mRequested;
    private long mStartedMs;
    private int mErrors;
    private int mGeneration;

    public UtubotCaptionsFollower(UtubotScheduler scheduler, Fetcher fetcher, Clock clock) {
        mScheduler = scheduler;
        mFetcher = fetcher;
        mClock = clock;
    }

    /**
     * The video starts: finds out where its captions are. The same video again changes nothing.
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
     * The user asked the backend for the captions of a video, which answered with this status. Only the video that plays is followed.
     */
    public void requested(String videoId, @Nullable String status) {
        if (!videoId.equals(mVideoId)) {
            return;
        }

        if (Captions.STATUS_QUEUED.equals(status) || Captions.STATUS_RUNNING.equals(status)) {
            mGeneration++; // an answer on its way may predate the job
            mRequested = true;
            mErrors = 0;
            mStartedMs = mClock.nowMs();
            scheduleNext();
        } else if (UtubotModels.STATUS_READY.equals(status)) {
            mRequested = true;
            mScheduler.remove(mPoll);
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
        mListener = null;
    }

    /**
     * Nothing more to wait for, but the video still plays: the user may yet ask for its captions
     */
    private void stopPolling() {
        mScheduler.remove(mPoll);
        mGeneration++;
        mRequested = false;
        mErrors = 0;
    }

    private void fetch() {
        String videoId = mVideoId;

        if (videoId == null) {
            return;
        }

        int generation = ++mGeneration;

        mFetcher.fetch(videoId, new Callback() {
            @Override
            public void onResult(Captions captions) {
                if (generation == mGeneration) {
                    onAnswer(videoId, captions);
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

    private void onAnswer(String videoId, Captions captions) {
        mErrors = 0;

        if (captions.isReady()) {
            Listener listener = mListener;
            boolean requested = mRequested;
            stop();

            if (listener != null) {
                listener.onCaptionsReady(videoId, captions, requested);
            }
        } else if (Captions.STATUS_QUEUED.equals(captions.status) || Captions.STATUS_RUNNING.equals(captions.status)) {
            mRequested = true;
            scheduleNext();
        } else {
            stopPolling();
        }
    }

    private void onFailure() {
        // Without a job to wait for the one answer is all there is to ask
        if (!mRequested || ++mErrors >= MAX_ERRORS) {
            stopPolling();
            return;
        }

        scheduleNext();
    }

    private void scheduleNext() {
        mScheduler.remove(mPoll);

        if (mClock.nowMs() - mStartedMs + POLL_INTERVAL_MS > MAX_FOLLOW_MS) {
            stopPolling();
            return;
        }

        mScheduler.postDelayed(mPoll, POLL_INTERVAL_MS);
    }
}
