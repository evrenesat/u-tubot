package com.liskovsoft.smartyoutubetv2.common.utubot;

/**
 * When the working badge may show: never over the player (a video playing or paused, and the dialogs on top of it), and
 * elsewhere only for requests the viewer waits for, once they have run longer than the show delay.
 */
public final class UtubotBadgePolicy {
    private UtubotBadgePolicy() {
    }

    public static boolean isAllowed(boolean isPlayerScreen, int count) {
        return !isPlayerScreen && count > 0;
    }

    /**
     * @param busySinceMs when the count last went above zero
     */
    public static boolean isDue(boolean isPlayerScreen, int count, long busySinceMs, long nowMs, long showDelayMs) {
        return isAllowed(isPlayerScreen, count) && nowMs - busySinceMs >= showDelayMs;
    }
}
