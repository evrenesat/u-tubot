package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.os.SystemClock;

import androidx.annotation.Nullable;

/**
 * The HQ captions of a video opened from a Processed tile are selected whatever "Select HQ captions automatically" says: the tile is
 * about what was processed, so its captions are what the user opens it for. A request is for one video and is taken by the player when
 * it sets that video; one that no player took expires, so it never carries to a later open of that video.
 */
public final class UtubotCaptionsOpen {
    /** The start of the playback follows the open at once; this bounds a request the player never took */
    public static final long EXPIRY_MS = 5_000;
    @Nullable
    private static String sVideoId;
    private static long sRequestedMs;

    private UtubotCaptionsOpen() {
    }

    /**
     * The tile open asks for the video's HQ captions to be selected. Another request replaces it.
     */
    public static synchronized void request(@Nullable String videoId) {
        sVideoId = videoId;
        sRequestedMs = SystemClock.uptimeMillis();
    }

    /**
     * Whether the request is this video's, taking it: the player reads it once when it sets the video and keeps it for that playback.
     */
    public static synchronized boolean take(@Nullable String videoId) {
        if (videoId == null || !videoId.equals(sVideoId)
                || SystemClock.uptimeMillis() - sRequestedMs > EXPIRY_MS) {
            return false;
        }

        sVideoId = null;

        return true;
    }

    public static synchronized void clear() {
        sVideoId = null;
    }
}
