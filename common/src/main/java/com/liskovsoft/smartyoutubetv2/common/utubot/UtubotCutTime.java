package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;

import java.util.List;

/**
 * Maps a position in the video to the position inside an active director's cut and the kept part the playback is in. A cut keeps a list of
 * parts and skips the rest (see ai/CONTRACT.md, "Director's cuts"), so the cut time is the sum of the kept parts before the current
 * position plus how far into the current part it is. This is what the player shows while a cut is on: the position and length in cut time
 * and the current part number, with the full-video time unchanged.
 */
public final class UtubotCutTime {
    private UtubotCutTime() {
    }

    /**
     * The playback's position inside the cut and which kept part it is in.
     */
    public static final class CutPosition {
        /** The position within the cut, 0 at the start of the first kept part */
        public final long cutPositionMs;
        /** The 1-based index of the kept part the position is in, 0 when it is in a dropped range or before the first / past the last part */
        public final int partIndex;
        /** The number of kept parts in the cut */
        public final int partCount;
        /** The kept length reached by walking the parts: the fallback when the cut reports no kept length */
        public final long totalKeptMs;

        public CutPosition(long cutPositionMs, int partIndex, int partCount, long totalKeptMs) {
            this.cutPositionMs = cutPositionMs;
            this.partIndex = partIndex;
            this.partCount = partCount;
            this.totalKeptMs = totalKeptMs;
        }
    }

    /**
     * @param videoPositionMs the current position in the video, milliseconds
     * @return the cut time (position within the cut) and the kept part the playback is in, or 0/0/0 when the cut has no parts
     */
    public static CutPosition of(@Nullable Cut cut, long videoPositionMs) {
        List<CutPart> parts = cut != null ? cut.parts : null;
        int partCount = parts != null ? parts.size() : 0;

        // The kept length is the sum of every part, computed first so it is the same whether the playback is in a part or in a drop.
        long totalKept = 0;

        if (parts != null) {
            for (CutPart part : parts) {
                totalKept += Math.max(0, part.endMs - part.startMs);
            }
        }

        long running = 0;

        if (parts != null) {
            for (int i = 0; i < partCount; i++) {
                CutPart part = parts.get(i);
                long start = part.startMs;
                long end = part.endMs;

                if (videoPositionMs < start) {
                    // Before this part: in a dropped range or before the first part. No later part counts, so the cut time is the
                    // kept length reached so far and the playback is not inside a kept part.
                    return new CutPosition(running, 0, partCount, totalKept);
                }

                if (videoPositionMs < end) {
                    return new CutPosition(running + (videoPositionMs - start), i + 1, partCount, totalKept);
                }

                running += end - start; // this part is fully behind the playback
            }
        }

        // Past the last part: the cut time is the full kept length and the playback is in the drop to the end.
        return new CutPosition(running, 0, partCount, totalKept);
    }
}
