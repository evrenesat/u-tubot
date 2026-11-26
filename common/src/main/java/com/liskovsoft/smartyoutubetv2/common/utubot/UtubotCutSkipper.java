package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import java.util.List;

/**
 * The skip decisions of an active director's cut, kept free of the player so the rules can be tested. A dropped range is skipped when
 * the playback crosses into its beginning by itself — a seek (or any other big move) wins and plays — and the jump goes past every
 * sponsor segment set to skip that overlaps or touches the destination, so there is one jump, not two.
 */
public final class UtubotCutSkipper {
    /**
     * A sponsor segment that starts this close after a jump destination is part of the same jump (the sponsor block groups its own
     * segments within the same window)
     */
    public static final long TOUCH_MS = 3_000;
    /**
     * A move of the playback longer than a tick of the highest speed cannot be the playback flowing: it is a seek
     */
    private static final long MAX_FLOW_MS = 5_000;

    /** What to do at a position: jump to another one, or keep playing */
    public static class Decision {
        private static final Decision PLAY = new Decision(-1);
        public final long jumpToMs;

        private Decision(long jumpToMs) {
            this.jumpToMs = jumpToMs;
        }

        public boolean isJump() {
            return jumpToMs >= 0;
        }

        public static Decision play() {
            return PLAY;
        }

        public static Decision jumpTo(long ms) {
            return new Decision(ms);
        }
    }

    /**
     * Decides whether a sponsor segment of the video is to be skipped (the sponsor block's per-category setting). Null: every segment
     * counts as skipped.
     */
    public interface SkipAction {
        boolean isSkipped(String category);
    }

    private final Cut mCut;
    private final List<SponsorSegment> mSponsorSegments;
    @Nullable
    private final SkipAction mSkipAction;
    private long mLastPositionMs = -1;

    public UtubotCutSkipper(Cut cut, List<SponsorSegment> sponsorSegments, @Nullable SkipAction skipAction) {
        mCut = cut;
        mSponsorSegments = sponsorSegments;
        mSkipAction = skipAction;
    }

    /**
     * The cut applies only to the video it was built for: a player length that differs by more than 2 s is not the same video (or a
     * different edition of it)
     */
    public static boolean matchesDuration(Cut cut, long durationMs) {
        return cut != null && cut.durationMs > 0 && durationMs > 0 && Math.abs(cut.durationMs - durationMs) <= 2_000;
    }

    /**
     * One step of the playback: whether to jump, and where. Only a crossing that the playback made by itself skips: the previous
     * position was before the drop and the current one is inside it. A seek (backwards, or any move a tick of the current speed
     * cannot explain) lands wherever it landed and plays. The position of a jump this decision causes is remembered, so the next
     * step compares against the destination, not against the place the jump started at.
     */
    public Decision onPosition(long positionMs, float speed) {
        long previous = mLastPositionMs;
        mLastPositionMs = positionMs;

        if (previous < 0 || positionMs < previous || positionMs - previous > (long) (MAX_FLOW_MS * Math.max(speed, 1f))) {
            return Decision.play();
        }

        for (long[] range : mCut.skipRangesMs) {
            // Any flowing tick that lands inside the drop is a crossing, however deep it landed:
            // a fast tick or a late one must not miss the drop and play all of it. A seek is
            // already set aside above (backwards, or more than a tick of this speed can move).
            if (previous < range[0] && positionMs >= range[0] && positionMs < range[1]) {
                long destination = destination(range[1]);
                mLastPositionMs = destination;
                return Decision.jumpTo(destination);
            }
        }

        return Decision.play();
    }

    /**
     * A seek the user made: it wins and plays wherever it landed, even a short forward seek that lands just inside a drop. The next
     * step compares against the landed position, so a later crossing of a drop is still skipped. Applying a cut is not a seek (see
     * {@link #onAppliedAt(long)}).
     */
    public Decision onSeek(long positionMs) {
        mLastPositionMs = positionMs;

        return Decision.play();
    }

    /**
     * The moment a cut is applied: an explicit act, not a seek. When the playback is already inside a dropped range — an intro drop
     * the video plays in, or a cut picked up mid-drop — it jumps once to the end of the drop, with the usual one-jump extension.
     * A drop that starts at 0 cannot be crossed by the flowing playback at all, so this is the only way it is ever skipped.
     */
    public Decision onAppliedAt(long positionMs) {
        mLastPositionMs = positionMs;

        for (long[] range : mCut.skipRangesMs) {
            if (positionMs >= range[0] && positionMs < range[1]) {
                long destination = destination(range[1]);
                mLastPositionMs = destination;
                return Decision.jumpTo(destination);
            }
        }

        return Decision.play();
    }

    /**
     * The end of a jump: past every sponsor segment set to skip that overlaps or touches the destination (and past a dropped range
     * that starts right there), so the sponsor skip's own watcher finds nothing to jump at where the jump lands.
     */
    public long destination(long fromMs) {
        long destination = fromMs;
        boolean extended = true;

        while (extended) {
            extended = false;

            for (long[] range : mCut.skipRangesMs) {
                if (range[0] > destination && range[0] <= destination + TOUCH_MS && range[1] > destination) {
                    destination = Math.max(destination, range[1]);
                    extended = true;
                }
            }

            if (mSponsorSegments == null) {
                continue;
            }

            for (SponsorSegment segment : mSponsorSegments) {
                if (isSkipped(segment) && segment.getStartMs() <= destination + TOUCH_MS && segment.getEndMs() > destination) {
                    destination = Math.max(destination, segment.getEndMs());
                    extended = true;
                }
            }
        }

        return destination;
    }

    private boolean isSkipped(SponsorSegment segment) {
        return mSkipAction == null || mSkipAction.isSkipped(segment.getCategory());
    }
}