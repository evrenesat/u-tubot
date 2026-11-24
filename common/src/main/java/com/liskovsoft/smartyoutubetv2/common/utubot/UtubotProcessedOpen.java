package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;

/**
 * Opening a tile of the Processed section (u-tubot#66): the video plays through the normal playback path, and its HQ captions are
 * selected even when "Select HQ captions automatically" is off. A ready director's cut is offered by {@link UtubotCutController} as
 * it is at any video start (#64): the controller follows the video through {@code GET /v1/videos/{id}/cuts} and announces a ready
 * cut with its one-press Apply dialog, or applies it by itself when "apply ready cuts automatically" is on. Nothing here carries or
 * applies a cut again.
 */
public final class UtubotProcessedOpen {
    public interface Player {
        void openVideo(Video video);
    }

    private UtubotProcessedOpen() {
    }

    /**
     * Whether the card is one of the Processed section's tiles: its group carries the section, also on a cached replay
     */
    public static boolean isProcessed(@Nullable Video item) {
        VideoGroup group = item != null ? item.getGroup() : null;
        BrowseSection section = group != null ? group.getSection() : null;

        return section != null && section.getId() == UtubotProcessedSection.ID;
    }

    /**
     * The open: the captions request goes with the video, and the playback starts through the opener (the normal playback path).
     */
    public static void open(@Nullable Video video, @Nullable Player player) {
        if (video == null || video.videoId == null || player == null) {
            return;
        }

        UtubotCaptionsOpen.request(video.videoId);
        player.openVideo(video);
    }

    public static void open(Context context, Video video) {
        open(video, PlaybackPresenter.instance(context)::openVideo);
    }
}
