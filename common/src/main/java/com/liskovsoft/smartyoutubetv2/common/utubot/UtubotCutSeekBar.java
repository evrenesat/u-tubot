package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerUI;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;

import java.util.ArrayList;
import java.util.List;

/**
 * The seek bar shows the sponsor block's own colours and, while a director's cut is active, the cut's dimmed skips next to them. The
 * sponsor block controller routes its writes through here: its reset for a new video keeps the cut of the same video, and its own
 * segments are laid over the cut's instead of replacing them. Outside the built-in flavor this is a pass-through: the sponsor block
 * behaves as it always has.
 */
public final class UtubotCutSeekBar {
    @Nullable
    private static volatile List<SeekBarSegment> sCutSegments;
    @Nullable
    private static volatile String sCutVideoId;
    @Nullable
    private static volatile List<SeekBarSegment> sSponsorSegments;

    private UtubotCutSeekBar() {
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