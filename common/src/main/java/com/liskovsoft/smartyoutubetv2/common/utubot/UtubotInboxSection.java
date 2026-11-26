package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxKind;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

/**
 * The TV's Inbox (u-tubot #160): one tile per ready AI result, newest first, with what the result is and its language under the title.
 * Unlike the Processed section (a video's results grouped), this is one tile per result, so a result can be opened after leaving the video.
 */
public final class UtubotInboxSection {
    /** A reserved sidebar id, past the Processed section (26) and the MediaGroup.TYPE_... ids (MediaGroup is a pinned sibling repo) */
    public static final int ID = 27;
    /** The backend's default count of items (ai/CONTRACT.md, GET /v1/inbox) */
    public static final int LIMIT = 50;
    private static final String SECONDARY_DELIM = " \u00b7 ";

    private UtubotInboxSection() {
    }

    /**
     * The section's tiles from the answer of {@code GET /v1/inbox}: in its order, newest first
     */
    public static VideoGroup toGroup(Context context, BrowseSection section, InboxList list) {
        List<Video> videos = new ArrayList<>();

        if (list != null) {
            for (InboxItem item : list.items) {
                if (item != null && item.videoId != null) {
                    videos.add(toVideo(context, item));
                }
            }
        }

        VideoGroup group = VideoGroup.from(videos, section, -1);
        group.setAction(VideoGroup.ACTION_REPLACE);
        group.setId(group.hashCode());
        group.setTitle(section != null ? section.getTitle() : context.getString(R.string.utubot_inbox_title));

        return group;
    }

    /**
     * A tile of the result: its id, title and thumbnail, what the result is and, for research and captions, its language, under the title
     */
    public static Video toVideo(Context context, InboxItem item) {
        Video video = new Video();
        video.videoId = item.videoId;
        video.title = item.title != null ? item.title : item.videoId;
        video.cardImageUrl = item.thumbnail;
        video.secondTitle = resultLabel(context, item);
        video.inboxKind = item.kind;
        video.inboxId = item.id;

        return video;
    }

    /**
     * What the result is, under the title: "Cut · Only the demo", "Summary · TL;DR", "Research · English", "Captions · English (HQ)".
     * The video's length is last when known: "Cut · Only the demo · 5:02"
     */
    public static String resultLabel(Context context, InboxItem item) {
        String kind;
        String detail;

        switch (item.kind) {
            case InboxKind.CUT:
                kind = context.getString(R.string.utubot_cut);
                detail = item.label != null && !item.label.trim().isEmpty() ? item.label.trim() : null;
                break;
            case InboxKind.SUMMARY:
                kind = context.getString(R.string.utubot_summary);
                detail = detailForSummary(context, item);
                break;
            case InboxKind.RESEARCH:
                kind = context.getString(R.string.utubot_research);
                detail = resultIdLabel(context, item.resultId);
                break;
            case InboxKind.CAPTIONS:
                kind = context.getString(R.string.utubot_captions);
                detail = resultIdLabel(context, item.resultId);
                break;
            default:
                return item.title != null ? item.title : item.videoId;
        }

        String label = detail != null ? kind + SECONDARY_DELIM + detail : kind;

        // The video's length, carried by the item (OWNER TEXT), last when known: "Cut · Only the demo · 5:02"
        if (item.lengthS != UtubotModels.UNKNOWN && item.lengthS > 0) {
            label = label + SECONDARY_DELIM + formatLength(item.lengthS);
        }

        return label;
    }

    /**
     * The video's length as m:ss, or h:m:ss past an hour, for the tile
     */
    private static String formatLength(int seconds) {
        long hours = TimeUnit.SECONDS.toHours(seconds);
        long minutes = TimeUnit.SECONDS.toMinutes(seconds) % 60;
        long secs = seconds % 60;

        return hours > 0
                ? String.format(Locale.ROOT, "%d:%02d:%02d", hours, minutes, secs)
                : String.format(Locale.ROOT, "%d:%02d", minutes, secs);
    }

    private static String detailForSummary(Context context, InboxItem item) {
        if (item.label != null && !item.label.trim().isEmpty()) {
            return item.label.trim();
        }

        // The backend stores the summary's prompt key as its result id, so fall back to it when there is no prompt key
        String key = item.promptKey != null && !item.promptKey.trim().isEmpty()
                ? item.promptKey.trim()
                : (item.resultId != null && !item.resultId.trim().isEmpty() ? item.resultId.trim() : null);

        return key;
    }

    /**
     * The language a research or caption result is in, from its result id; the fallback is the raw id
     */
    private static String resultIdLabel(Context context, String resultId) {
        if (resultId == null || resultId.trim().isEmpty()) {
            return null;
        }

        String code = resultId.trim();
        Locale locale = new Locale(code.contains("-") ? code.substring(0, code.indexOf('-')) : code);

        return locale.getDisplayName(Locale.ROOT);
    }
}
