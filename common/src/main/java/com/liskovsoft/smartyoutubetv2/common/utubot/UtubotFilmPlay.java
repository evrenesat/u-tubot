package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * What the main player needs to play a film or an episode from a direct stream (a Real-Debrid link): the stream, the title it belongs to and
 * where to start. A {@code Video} that carries one skips the YouTube format load (see {@code VideoLoaderController}) and keeps its position in
 * {@link UtubotFilmsProgress}, not in the YouTube history.
 *
 * <p>The stream address can carry a key: it is never logged or shown.
 */
public final class UtubotFilmPlay {
    public static final String SOURCE_KIND = "film";
    /** The backend's id of a release starts with this, then the first hex digits of the SHA-256 of {@code sourceKey|releaseKey} */
    public static final String VIDEO_ID_PREFIX = "f";
    public static final int VIDEO_ID_HEX_CHARS = 10;

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
    private volatile float mStreamFps;
    private volatile String mSubtitleLanguage = "";
    private volatile String mYear = "";
    private volatile String mEpisodeTitle = "";

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
        UtubotFilmPlay film = new UtubotFilmPlay(progressId, type, titleId, name, poster, season, episode, url, streamName, startMs, sizeBytes);
        film.setCatalogue(mYear, mEpisodeTitle);

        return film;
    }

    /** What the catalogue says for the player's title: the film's year and the episode's title; either may be empty */
    public void setCatalogue(@Nullable String year, @Nullable String episodeTitle) {
        mYear = year == null ? "" : year.trim();
        mEpisodeTitle = episodeTitle == null ? "" : episodeTitle.trim();
    }

    public String year() {
        return mYear;
    }

    public String episodeTitle() {
        return mEpisodeTitle;
    }

    /** The title line of the player (see {@link UtubotFilmTitle}) */
    public String displayTitle() {
        return UtubotFilmTitle.title(this);
    }

    /** The format chips of the player's second line */
    public String displayChips() {
        return UtubotFilmTitle.chips(streamName, sizeBytes);
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

    /**
     * The backend's id of this release (as {@code film_video_id} in the backend): eleven characters, derived from the source and the
     * release, so cuts, their choice and the transcript are per release and never mistaken for a YouTube video. Not the progress id:
     * the position of a title is kept per title, the cut per stream file.
     */
    public String videoId() {
        return filmVideoId(sourceKey(), releaseKey());
    }

    public static String filmVideoId(String sourceKey, String releaseKey) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest((sourceKey + "|" + releaseKey).getBytes(StandardCharsets.UTF_8));
            StringBuilder id = new StringBuilder(VIDEO_ID_PREFIX);

            for (int i = 0; i < VIDEO_ID_HEX_CHARS / 2; i++) {
                id.append(String.format("%02x", digest[i]));
            }

            return id.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** The frame rate of the stream's video once the player has opened it, 0 when unknown */
    public float streamFps() {
        return mStreamFps;
    }

    public void setStreamFps(float fps) {
        if (fps > 0) {
            mStreamFps = fps;
        }
    }

    /** The viewer's subtitle language (two letters) for the subtitles the backend looks up, empty for the backend's English */
    public String subtitleLanguage() {
        return mSubtitleLanguage;
    }

    public void setSubtitleLanguage(@Nullable String language) {
        mSubtitleLanguage = language == null ? "" : language;
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
