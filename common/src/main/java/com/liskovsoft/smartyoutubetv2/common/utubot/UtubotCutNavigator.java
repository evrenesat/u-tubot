package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;

/**
 * Where the kept parts of an applied director's cut are, kept free of the player so the rules can be tested: the next part after
 * the playback, the part before it, and whether the playback sits in a cut-out range (the badge).
 */
public final class UtubotCutNavigator {
    /** No part in that direction */
    public static final long NONE = -1;

    private UtubotCutNavigator() {
    }

    /**
     * The playback sits in one of the ranges the cut skips
     */
    public static boolean isInCut(Cut cut, long positionMs) {
        if (cut == null) {
            return false;
        }

        for (long[] range : cut.skipRangesMs) {
            if (range != null && positionMs >= range[0] && positionMs < range[1]) {
                return true;
            }
        }

        return false;
    }

    /**
     * The start of the kept part after the playback: the following part when it is in a kept one, the next one when it is in a cut-out
     */
    public static long nextPartStartMs(Cut cut, long positionMs) {
        if (cut == null) {
            return NONE;
        }

        long next = NONE;

        for (CutPart part : cut.parts) {
            if (part != null && part.startMs > positionMs && (next == NONE || part.startMs < next)) {
                next = part.startMs;
            }
        }

        return next;
    }

    /**
     * The start of the kept part before the playback: the part before the one it is in, or the one the cut-out follows
     */
    public static long previousPartStartMs(Cut cut, long positionMs) {
        if (cut == null) {
            return NONE;
        }

        long previous = NONE;

        for (CutPart part : cut.parts) {
            if (part != null && part.endMs <= positionMs && (previous == NONE || part.startMs > previous)) {
                previous = part.startMs;
            }
        }

        return previous;
    }

    /**
     * What the "outside the cut" badge says at a position: visible only inside a cut-out range, with the next kept part when there is one.
     */
    public static Badge badgeAt(Cut cut, long positionMs) {
        if (!isInCut(cut, positionMs)) {
            return Badge.hidden();
        }

        long next = nextPartStartMs(cut, positionMs);

        return next == NONE ? Badge.withoutNext() : Badge.toPart(next, next - positionMs);
    }

    public static final class Badge {
        public final boolean visible;
        public final long nextPartStartMs;
        public final long remainingMs;

        private Badge(boolean visible, long nextPartStartMs, long remainingMs) {
            this.visible = visible;
            this.nextPartStartMs = nextPartStartMs;
            this.remainingMs = remainingMs;
        }

        public static Badge hidden() {
            return new Badge(false, NONE, NONE);
        }

        public static Badge toPart(long nextPartStartMs, long remainingMs) {
            return new Badge(true, nextPartStartMs, remainingMs);
        }

        public static Badge withoutNext() {
            return new Badge(true, NONE, NONE);
        }

        public boolean hasNext() {
            return nextPartStartMs != NONE;
        }
    }
}
