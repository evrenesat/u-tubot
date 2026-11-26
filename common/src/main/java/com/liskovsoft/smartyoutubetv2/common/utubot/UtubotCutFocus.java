package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

/**
 * The card focused on a thumbnail/browse screen, for the cut-ready auto-start (issue 197): a cut ordered from the thumbnail screen opens
 * by itself when it is ready, but only while the owner is still browsing (a card focused, no video playing). The panel controller reports
 * the focused card on every focus change; the player screen and every other screen clear it on pause, so a stale card never starts a cut
 * the owner moved away from.
 */
public final class UtubotCutFocus {
    @Nullable private static volatile String sFocusedVideoId;

    private UtubotCutFocus() {
    }

    /**
     * The card the browse screen is focused on, or null when the focus is not on a card (a dialog, the player, or nothing). Called from
     * the TV's panel controller only.
     */
    public static void set(@Nullable String videoId) {
        sFocusedVideoId = videoId;
    }

    /**
     * The card the browse screen is focused on, or null when no card has the focus
     */
    @Nullable
    static String currentVideoId() {
        return sFocusedVideoId;
    }
}
