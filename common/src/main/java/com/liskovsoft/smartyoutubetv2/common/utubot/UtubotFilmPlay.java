package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

/**
 * What the main player needs to play a film or an episode from a direct stream (a Real-Debrid link): the stream, the title it belongs to and
 * where to start. A {@code Video} that carries one skips the YouTube format load (see {@code VideoLoaderController}) and keeps its position in
 * {@link UtubotFilmsProgress}, not in the YouTube history.
 *
 * <p>The stream address can carry a key: it is never logged or shown.
 */
public final class UtubotFilmPlay {
    /** The prefix of a film's video id, so it is never mistaken for a YouTube id */
    public static final String SOURCE_KIND = "film";
    public static final String VIDEO_ID_PREFIX = "utubot-film:";

    /** The key in {@link UtubotFilmsProgress}: a film's IMDb id, an episode's {@code tt0000000:season:episode} */
    public final String progressId;
    public final String type;
    /** The film or series id the entry belongs to */
    public final String titleId;
    public final String name;
    @Nullable
    public final String poster;
    public final int season;
    public final int episode;
    public final String streamUrl;
    public final String streamName;
    public final long startMs;
    /** The size of the stream file, 0 when the addon did not say */
    public final long sizeBytes;
    private volatile long mReleaseDurationMs;

    public UtubotFilmPlay(String progressId, String type, String titleId, String name, @Nullable String poster, int season, int episode,
                          String streamUrl, String streamName, long startMs, long sizeBytes) {
        this.progressId = progressId == null ? "" : progressId;
        this.type = type == null ? UtubotRealDebridClient.TYPE_MOVIE : type;
        this.titleId = titleId == null || titleId.isEmpty() ? this.progressId : titleId;
        this.name = name == null ? "" : name;
        this.poster = poster;
        this.season = season;
        this.episode = episode;
        this.streamUrl = streamUrl == null ? "" : streamUrl;
        this.streamName = streamName == null ? "" : streamName;
        this.startMs = Math.max(0, startMs);
        this.sizeBytes = Math.max(0, sizeBytes);
    }

    /** The same title on another stream, from where the viewer is */
    public UtubotFilmPlay withStream(String url, String streamName, long sizeBytes, long startMs) {
        return new UtubotFilmPlay(progressId, type, titleId, name, poster, season, episode, url, streamName, startMs, sizeBytes);
    }

    /** The backend's {@code source_kind} of a cut: the source is a film, not a YouTube video */
    public String sourceKind() {
        return SOURCE_KIND;
    }

    /** The backend's {@code source_key}: {@code imdb:tt1234567} for a film, {@code imdb:tt1234567:S1E2} for an episode */
    public String sourceKey() {
        return "imdb:" + titleId + (isSeries() && season > 0 ? ":S" + season + "E" + episode : "");
    }

    /** The backend's {@code release_key}: the stream file name, and its size when known; a cut fits one release */
    public String releaseKey() {
        return sizeBytes > 0 ? streamName + "|" + sizeBytes : streamName;
    }

    /** The backend's {@code release_duration_ms}: the length of this release once the player knows it, else 0 */
    public long releaseDurationMs() {
        return mReleaseDurationMs;
    }

    public void setReleaseDurationMs(long durationMs) {
        if (durationMs > 0) {
            mReleaseDurationMs = durationMs;
        }
    }

    public String videoId() {
        return VIDEO_ID_PREFIX + progressId;
    }

    public boolean isSeries() {
        return UtubotRealDebridClient.TYPE_SERIES.equals(type);
    }

    /** "Name", or "Name  S2 E5" for an episode */
    public String title() {
        return isSeries() && season > 0 ? name + "  S" + season + " E" + episode : name;
    }

    /** Remembers where the viewer is, for Resume, the watched mark and Continue watching; false when the length is not known yet */
    public boolean saveProgress(UtubotFilmsProgress progress, long positionMs, long durationMs, long now) {
        if (progressId.isEmpty() || durationMs <= 0 || positionMs < 0) {
            return false;
        }

        progress.save(progressId, type, titleId, name, poster, season, episode, Math.min(positionMs, durationMs), durationMs, now);
        return true;
    }

    /** Where playback starts: the resume point stored for this id, otherwise the start the play was opened with */
    public long resumeFrom(UtubotFilmsProgress progress) {
        if (startMs > 0) {
            return startMs;
        }

        UtubotFilmsProgress.Entry entry = progress.get(progressId);
        return entry == null ? 0 : entry.resumeMs();
    }
}
