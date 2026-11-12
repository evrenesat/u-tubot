package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import java.util.Locale;
import java.util.concurrent.TimeUnit;

/**
 * The contract's VideoMeta of a card
 */
public final class UtubotMeta {
    private static final String VIEWS_WORD = "view";
    private static final String CLOCK_DELIMITER = ":";
    private static final int SECONDS_PER_MINUTE = 60;

    private UtubotMeta() {
    }

    @Nullable
    public static VideoMeta from(@Nullable Video video) {
        if (video == null || video.videoId == null || video.isChapter) {
            return null;
        }

        VideoMeta meta = new VideoMeta();
        meta.videoId = video.videoId;
        meta.title = video.getTitle();
        meta.channel = video.getAuthor();
        meta.channelId = video.channelId;
        meta.durationSec = durationSec(video);
        meta.isShort = video.isShorts;
        meta.isLive = video.isLive;
        meta.description = video.description;
        fillStats(meta, video.getSecondTitle());
        return meta;
    }

    /**
     * The length of a video in seconds, 0 when not known. The backend's automatic transcription needs it: it only starts for a video
     * of known length. A card carries it in its own field, in its media item (a copy of a card keeps the item but not the field) or in
     * the clock of its badge.
     */
    static long durationSec(Video video) {
        long durationMs = video.getDurationMs();

        if (durationMs <= 0 && video.mediaItem != null) {
            durationMs = video.mediaItem.getDurationMs();
        }

        return durationMs > 0 ? TimeUnit.MILLISECONDS.toSeconds(durationMs) : parseClock(video.badge);
    }

    /**
     * The second title is "Author • 1.2M views • 3 days ago": the part with "view" in it, and the one after it
     */
    static void fillStats(VideoMeta meta, @Nullable CharSequence secondTitle) {
        if (secondTitle == null) {
            return;
        }

        String[] parts = secondTitle.toString().split(Video.TERTIARY_TEXT_DELIM);

        for (int i = 0; i < parts.length; i++) {
            String part = parts[i].trim();

            if (part.toLowerCase(Locale.ROOT).contains(VIEWS_WORD)) {
                meta.views = part;

                if (i + 1 < parts.length) {
                    meta.published = parts[i + 1].trim();
                }
            }
        }
    }

    /**
     * @return the seconds of a badge like "12:34" or "1:02:03", 0 when it isn't one
     */
    static long parseClock(@Nullable String text) {
        if (text == null || !text.contains(CLOCK_DELIMITER)) {
            return 0;
        }

        long seconds = 0;

        for (String part : text.trim().split(CLOCK_DELIMITER)) {
            try {
                seconds = seconds * SECONDS_PER_MINUTE + Long.parseLong(part.trim());
            } catch (NumberFormatException e) {
                return 0;
            }
        }

        return seconds;
    }
}
