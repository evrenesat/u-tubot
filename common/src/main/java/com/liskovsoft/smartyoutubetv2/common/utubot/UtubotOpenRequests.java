package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;

/**
 * A request to open the Summary view or the AI answer, made from the video menu (a dialog over the browse screen). The screen
 * underneath opens it when it resumes; a request nobody took in time is dropped.
 */
public final class UtubotOpenRequests {
    public enum Kind {
        SUMMARY, ANSWER
    }

    public static final class Request {
        public final Kind kind;
        public final Video video;
        private final long mCreatedMs;

        Request(Kind kind, Video video, long createdMs) {
            this.kind = kind;
            this.video = video;
            mCreatedMs = createdMs;
        }
    }

    public static final long EXPIRY_MS = 5_000;
    private Request mPending;

    public synchronized void post(Kind kind, Video video, long nowMs) {
        mPending = new Request(kind, video, nowMs);
    }

    /**
     * The request, once
     */
    @Nullable
    public synchronized Request take(long nowMs) {
        Request request = mPending;
        mPending = null;

        return request != null && nowMs - request.mCreatedMs <= EXPIRY_MS ? request : null;
    }

    public synchronized void clear() {
        mPending = null;
    }
}
