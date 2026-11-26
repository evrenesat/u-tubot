package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxKind;

/**
 * Opening a tile of the Inbox section (u-tubot #160): the result is already ready, so the open resumes it where it stands. A cut or a
 * caption result opens the video, and the player applies or offers the ready cut and selects the ready HQ captions (as at any video start,
 * like the Processed section). A summary or a research result shows its result over the screen the tile is on, like the menu's summary and
 * answer: the request is taken by that screen, which stays under the player, so the video is not started here.
 */
public final class UtubotInboxOpen {
    public interface Player {
        void openVideo(Video video);
    }

    private UtubotInboxOpen() {
    }

    /**
     * Whether the card is one of the Inbox section's tiles: its group carries the section, also on a cached replay
     */
    public static boolean isInbox(@Nullable Video item) {
        VideoGroup group = item != null ? item.getGroup() : null;
        BrowseSection section = group != null ? group.getSection() : null;

        return section != null && section.getId() == UtubotInboxSection.ID;
    }

    /**
     * The open without a known result: a cut or a caption result opens the video, else nothing is known and the video opens too
     */
    public static void open(@Nullable Video video, @Nullable Player player) {
        open(video, player, null);
    }

    /**
     * The open of a known result (see the class doc): show a summary or a research result, open the video for a cut or a caption result
     */
    public static void open(@Nullable Video video, @Nullable Player player, @Nullable InboxItem item) {
        if (video == null || video.videoId == null || player == null) {
            return;
        }

        // The kind is known from the caller, else carried on the tile (see UtubotInboxSection.toVideo)
        String kind = item != null ? item.kind : video.inboxKind;

        if (InboxKind.SUMMARY.equals(kind)) {
            UtubotUiHost.request(UtubotOpenRequests.Kind.SUMMARY, video);
            return;
        }

        if (InboxKind.RESEARCH.equals(kind)) {
            UtubotUiHost.request(UtubotOpenRequests.Kind.ANSWER, video);
            return;
        }

        if (InboxKind.CAPTIONS.equals(kind)) {
            // The ready HQ captions are selected, like the Processed section.
            UtubotCaptionsOpen.request(video.videoId);
        }

        player.openVideo(video);
    }

    public static void open(Context context, Video video) {
        open(video, PlaybackPresenter.instance(context)::openVideo);
    }

    public static void open(Context context, Video video, InboxItem item) {
        open(video, PlaybackPresenter.instance(context)::openVideo, item);
    }
}
