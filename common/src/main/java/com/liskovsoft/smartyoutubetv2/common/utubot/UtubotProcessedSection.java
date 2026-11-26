package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.googlecommon.common.helpers.ServiceHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutState;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.JobState;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCaption;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutMode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * The TV's Processed section (u-tubot #66): the videos a user recently processed, one tile each, newest first, with what was
 * processed and its state under the title.
 */
public final class UtubotProcessedSection {
    /** A reserved sidebar id, past the MediaGroup.TYPE_... ids (MediaGroup is a pinned sibling repo) */
    public static final int ID = 26;
    /** The backend's default count of videos (ai/CONTRACT.md, GET /v1/processed) */
    public static final int LIMIT = 50;
    private static final String PART_DELIM = " " + Video.TERTIARY_TEXT_DELIM + " ";
    private static final String LABEL_DELIM = ", ";

    private UtubotProcessedSection() {
    }

    /**
     * The section's tiles from the answer of {@code GET /v1/processed}: in its order, newest last change first
     */
    public static VideoGroup toGroup(Context context, BrowseSection section, ProcessedList list) {
        List<Video> videos = new ArrayList<>();

        if (list != null) {
            for (ProcessedItem item : list.videos) {
                if (item != null && item.videoId != null) {
                    videos.add(toVideo(context, item));
                }
            }
        }

        VideoGroup group = VideoGroup.from(videos, section, -1);
        group.setAction(VideoGroup.ACTION_REPLACE);
        group.setId(group.hashCode());
        group.setTitle(section != null ? section.getTitle() : context.getString(R.string.utubot_processed_title));

        return group;
    }

    /**
     * A tile of the video: its id, title and thumbnail, the processed line as the second title. The endpoint sends no channel, so
     * the tile has none.
     */
    public static Video toVideo(Context context, ProcessedItem item) {
        Video video = new Video();
        video.videoId = item.videoId;
        video.title = item.title != null ? item.title : item.videoId;
        video.cardImageUrl = item.thumbnail;
        video.secondTitle = processedText(context, item);
        if (item.durationSec != UtubotModels.UNKNOWN) {
            video.badge = ServiceHelper.millisToTimeText(item.durationSec * 1000);
        }

        return video;
    }

    /**
     * What was processed and where it stands: "HQ captions: ready • Cut ready: Only the demo • Summary ready"
     */
    public static String processedText(Context context, ProcessedItem item) {
        List<String> parts = new ArrayList<>();
        String captions = captionsText(context, item);
        String cuts = cutsText(context, item);

        if (captions != null) {
            parts.add(captions);
        }

        if (cuts != null) {
            parts.add(cuts);
        }

        if (item != null && item.summary) {
            parts.add(context.getString(R.string.utubot_processed_summary));
        }

        return String.join(PART_DELIM, parts);
    }

    /**
     * "HQ captions: ready" when any of its jobs is ready, else the state of the newest job (the backend lists them newest first)
     */
    @Nullable
    private static String captionsText(Context context, ProcessedItem item) {
        if (item == null || item.captions.isEmpty()) {
            return null;
        }

        for (ProcessedCaption caption : item.captions) {
            if (caption.isReady()) {
                return context.getString(R.string.utubot_captions_status, JobState.READY);
            }
        }

        // Newest first: the latest job's state when none has captions to show
        return context.getString(R.string.utubot_captions_status, item.captions.get(0).state);
    }

    /**
     * "Cut ready: Only the demo, Short version" for every ready cut, else the state of the newest cut with its preset or prompt
     */
    @Nullable
    private static String cutsText(Context context, ProcessedItem item) {
        if (item == null || item.cuts.isEmpty()) {
            return null;
        }

        Set<String> readyLabels = new LinkedHashSet<>();

        for (ProcessedCut cut : item.cuts) {
            if (cut.isReady()) {
                readyLabels.add(cutLabel(context, cut));
            }
        }

        if (!readyLabels.isEmpty()) {
            return context.getString(R.string.utubot_processed_cut_ready, String.join(LABEL_DELIM, readyLabels));
        }

        ProcessedCut newest = item.cuts.get(0);
        String label = cutLabel(context, newest);

        switch (newest.state) {
            case CutState.WAITING:
                return context.getString(R.string.utubot_processed_cut_waiting, label);
            case CutState.BUILDING:
                return context.getString(R.string.utubot_processed_cut_building, label);
            case CutState.NEEDS_TRANSCRIPT:
                return context.getString(R.string.utubot_processed_cut_needs_transcript, label);
            case CutState.FAILED:
                return context.getString(R.string.utubot_processed_cut_failed, label);
            default:
                return context.getString(R.string.utubot_processed_cut, label);
        }
    }

    private static String cutLabel(Context context, ProcessedCut cut) {
        String label;
        if (cut.presetLabel != null && !cut.presetLabel.trim().isEmpty()) {
            label = cut.presetLabel.trim();
        } else if (cut.prompt != null && !cut.prompt.trim().isEmpty()) {
            label = cut.prompt.trim();
        } else {
            label = context.getString(R.string.utubot_cut);
        }
        return CutMode.WATCHED.equals(cut.mode)
                ? label + context.getString(R.string.utubot_cut_watched_suffix)
                : label;
    }
}
