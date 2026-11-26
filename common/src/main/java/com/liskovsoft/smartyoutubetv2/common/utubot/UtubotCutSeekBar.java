package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerUI;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;

import java.util.ArrayList;
import java.util.List;

/**
 * The seek bar shows the sponsor block's own colours and, while a director's cut is active, the cut's dimmed skips next to them. The
 * sponsor block controller routes its writes through here: its reset for a new video keeps the cut of the same video, and its own
 * segments are laid over the cut's instead of replacing them. Outside the built-in flavor this is a pass-through: the sponsor block
 * behaves as it always has.
 */
public final class UtubotCutSeekBar {
    /** The kept parts: bright, clearly the video the cut keeps */
    public static final int KEPT_COLOR = 0xFF26C6DA;
    /** The cut-out ranges: dark and hatched, never mistaken for a kept part */
    public static final int CUT_COLOR = 0xCC14181C;
    @Nullable
    private static volatile List<SeekBarSegment> sCutSegments;
    @Nullable
    private static volatile String sCutVideoId;
    @Nullable
    private static volatile List<SeekBarSegment> sSponsorSegments;

    private UtubotCutSeekBar() {
    }

    /**
     * What the seek bar draws for a cut: the kept parts bright and the cut-out ranges dark and hatched. The cut-outs come last so
     * a shared boundary belongs to the cut-out. A duration of zero (not known yet) draws nothing.
     */
    public static List<SeekBarSegment> segmentsFor(@Nullable Cut cut, long durationMs) {
        List<SeekBarSegment> segments = new ArrayList<>();

        if (cut == null || durationMs <= 0) {
            return segments;
        }

        List<long[]> keptRanges = new ArrayList<>();

        for (CutPart part : cut.parts) {
            if (part != null && part.endMs > part.startMs) {
                keptRanges.add(new long[]{part.startMs, part.endMs});
            }
        }

        if (keptRanges.isEmpty()) {
            keptRanges = complement(cut.skipRangesMs, durationMs);
        }

        for (long[] range : keptRanges) {
            addSegment(segments, range[0], range[1], durationMs, KEPT_COLOR, false);
        }

        for (long[] range : cut.skipRangesMs) {
            addSegment(segments, range[0], range[1], durationMs, CUT_COLOR, true);
        }

        return segments;
    }

    private static List<long[]> complement(List<long[]> skipRangesMs, long durationMs) {
        List<long[]> kept = new ArrayList<>();
        long position = 0;

        for (long[] range : skipRangesMs) {
            if (range != null && range[0] > position) {
                kept.add(new long[]{position, range[0]});
            }

            if (range != null) {
                position = Math.max(position, range[1]);
            }
        }

        if (position < durationMs) {
            kept.add(new long[]{position, durationMs});
        }

        return kept;
    }

    private static void addSegment(List<SeekBarSegment> segments, long startMs, long endMs, long durationMs, int color, boolean hatched) {
        float startProgress = clamp(startMs / (float) durationMs);
        float endProgress = clamp(endMs / (float) durationMs);

        if (endProgress <= startProgress) {
            return;
        }

        SeekBarSegment segment = new SeekBarSegment();
        segment.startProgress = startProgress;
        segment.endProgress = endProgress;
        segment.color = color;
        segment.hatched = hatched;
        segments.add(segment);
    }

    private static float clamp(float progress) {
        return Math.max(0f, Math.min(1f, progress));
    }

    /**
     * The cut controller says what the cut of a video draws on the seek bar. Null clears it (the video is gone or the cut is off).
     */
    public static void setCut(@Nullable String videoId, @Nullable List<SeekBarSegment> segments) {
        if (segments == null) {
            sCutSegments = null;
            sCutVideoId = null;
        } else {
            sCutSegments = segments;
            sCutVideoId = videoId;
        }
    }

    /**
     * The sponsor block's reset for a video: the colours of the previous video go, but an active cut of the same video stays.
     */
    public static void wipe(PlayerUI player, @Nullable Video video) {
        if (video == null || !video.videoId.equals(sCutVideoId)) {
            sSponsorSegments = null; // the sponsor colours belonged to the previous video
            player.setSeekBarSegments(null);
        } else {
            paint(player); // the cut and the sponsor colours of this video stay
        }
    }

    /**
     * The sponsor block's own segments: shown next to the cut's, which stay under them.
     */
    public static void setSponsor(PlayerUI player, @Nullable List<SeekBarSegment> sponsorSegments) {
        sSponsorSegments = sponsorSegments;
        paint(player);
    }

    /**
     * Writes what the seek bar shows now: the cut's dimmed skips over the sponsor block's colours. The cut controller calls it when a
     * cut is applied or taken off, because the sponsor block's own writes do not reach the bar then.
     */
    public static void paint(PlayerUI player) {
        List<SeekBarSegment> cut = sCutSegments;

        if (cut == null || cut.isEmpty()) {
            player.setSeekBarSegments(sSponsorSegments);
            return;
        }

        List<SeekBarSegment> both = new ArrayList<>(cut);

        if (sSponsorSegments != null) {
            both.addAll(sSponsorSegments);
        }

        player.setSeekBarSegments(both);
    }
}