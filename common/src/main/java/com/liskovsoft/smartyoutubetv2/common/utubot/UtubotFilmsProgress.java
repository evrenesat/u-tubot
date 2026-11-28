package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * Where the owner stopped in each film or episode, kept on this TV: the resume position, the "watched" mark, and the "Continue watching" row.
 * One entry per playable id (a film's IMDb id, an episode's {@code tt0000000:season:episode}).
 */
public class UtubotFilmsProgress {
    /** Past this share of the running time a title counts as watched */
    public static final float WATCHED_SHARE = 0.9f;
    /** Before this the position is not worth resuming from */
    public static final long MIN_RESUME_MS = 30_000;
    private static final String PREFS = "utubot_films_progress";

    /** One stopped title */
    public static final class Entry {
        public final String id;
        public final String type;
        /** The film or series id the entry belongs to (the same as {@link #id} for a film) */
        public final String titleId;
        public final String name;
        public final String poster;
        public final int season;
        public final int episode;
        public final long positionMs;
        public final long durationMs;
        public final long updatedAt;

        Entry(String id, String type, String titleId, String name, String poster, int season, int episode, long positionMs, long durationMs,
              long updatedAt) {
            this.id = id;
            this.type = type;
            this.titleId = titleId;
            this.name = name;
            this.poster = poster;
            this.season = season;
            this.episode = episode;
            this.positionMs = positionMs;
            this.durationMs = durationMs;
            this.updatedAt = updatedAt;
        }

        public boolean isWatched() {
            return durationMs > 0 && positionMs >= durationMs * WATCHED_SHARE;
        }

        /** Where to start: 0 when there is too little to resume or the title is finished */
        public long resumeMs() {
            return isWatched() || positionMs < MIN_RESUME_MS ? 0 : positionMs;
        }

        /** "40 min left", "1 h 5 min left"; empty when the running time is unknown */
        public String timeLeft() {
            return UtubotFilmsProgress.timeLeft(durationMs - positionMs);
        }

        public float share() {
            return durationMs <= 0 ? 0f : Math.min(1f, positionMs / (float) durationMs);
        }
    }

    private static final long MINUTE_MS = 60_000;
    private static final long HOUR_MINUTES = 60;

    private static final String EPISODES_PREFS = "utubot_films_episodes";
    private static final String DISMISSED_PREFS = "utubot_films_dismissed";

    private final SharedPreferences mPrefs;
    /** The episode list of each series the viewer opened, so the row can name the next episode without the network */
    private final SharedPreferences mEpisodes;
    /** When the viewer removed a title from the row; watching it again brings it back */
    private final SharedPreferences mDismissed;

    public UtubotFilmsProgress(Context context) {
        mPrefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        mEpisodes = context.getSharedPreferences(EPISODES_PREFS, Context.MODE_PRIVATE);
        mDismissed = context.getSharedPreferences(DISMISSED_PREFS, Context.MODE_PRIVATE);
    }

    /** One card of the "Continue watching" row: what to open (the entry's title) and which episode comes up */
    public static final class Row {
        /** The title's latest entry: unfinished, or the last finished episode when {@link #next} */
        public final Entry entry;
        public final String titleId;
        public final String name;
        public final String type;
        public final String poster;
        /** The episode to open; 0 for a film */
        public final int season;
        public final int episode;
        public final String episodeTitle;
        /** The last episode was finished and this is the one after it */
        public final boolean next;

        Row(Entry entry, int season, int episode, String episodeTitle, boolean next) {
            this.entry = entry;
            this.titleId = entry.titleId;
            this.name = entry.name;
            this.type = entry.type;
            this.poster = entry.poster;
            this.season = season;
            this.episode = episode;
            this.episodeTitle = episodeTitle;
            this.next = next;
        }

        /** "Next: S01E02 Title", "S01E02 - 20 min left" or a film's time left */
        public String subtitle() {
            if (season <= 0) {
                return entry.timeLeft();
            }

            String code = String.format(java.util.Locale.US, "S%02dE%02d", season, episode);

            if (next) {
                return "Next: " + code + (episodeTitle.isEmpty() ? "" : " " + episodeTitle);
            }

            String left = entry.timeLeft();

            return left.isEmpty() ? code : code + " - " + left;
        }

        /** The share of the progress bar: none for an episode that has not been started */
        public float share() {
            return next ? 0f : entry.share();
        }
    }

    /** Keeps the episode list of a series; the row uses it to find the next episode */
    public void rememberEpisodes(String titleId, List<UtubotFilmsCatalog.Episode> episodes) {
        if (titleId == null || titleId.isEmpty() || episodes == null || episodes.isEmpty()) {
            return;
        }

        JSONArray list = new JSONArray();

        for (UtubotFilmsCatalog.Episode episode : episodes) {
            list.put(new JSONArray().put(episode.season).put(episode.number).put(episode.title == null ? "" : episode.title)
                    .put(episode.releasedMs));
        }

        mEpisodes.edit().putString(titleId, list.toString()).apply();
    }

    private List<UtubotFilmsCatalog.Episode> episodesOf(String titleId) {
        List<UtubotFilmsCatalog.Episode> episodes = new ArrayList<>();
        String text = mEpisodes.getString(titleId, null);

        if (text == null) {
            return episodes;
        }

        try {
            JSONArray list = new JSONArray(text);

            for (int i = 0; i < list.length(); i++) {
                JSONArray item = list.getJSONArray(i);
                episodes.add(new UtubotFilmsCatalog.Episode(item.getInt(0), item.getInt(1), item.optString(2, ""), item.optLong(3, 0)));
            }
        } catch (JSONException e) {
            episodes.clear();
        }

        Collections.sort(episodes, (a, b) -> a.season != b.season ? Integer.compare(a.season, b.season) : Integer.compare(a.number, b.number));

        return episodes;
    }

    /** Takes a title out of the row; watching it again puts it back */
    public void removeFromContinue(String titleId, long now) {
        if (titleId != null && !titleId.isEmpty()) {
            mDismissed.edit().putLong(titleId, now).apply();
        }
    }

    public void save(String id, String type, String titleId, String name, String poster, int season, int episode, long positionMs, long durationMs,
                     long now) {
        if (id == null || id.isEmpty() || durationMs <= 0 || positionMs < 0) {
            return;
        }

        try {
            JSONObject json = new JSONObject()
                    .put("type", type).put("titleId", titleId).put("name", name).put("poster", poster == null ? "" : poster)
                    .put("season", season).put("episode", episode).put("position", positionMs).put("duration", durationMs).put("updated", now);
            mPrefs.edit().putString(id, json.toString()).apply();
        } catch (JSONException e) {
            // a title with unusable text is not remembered
        }
    }

    @Nullable
    public Entry get(String id) {
        return parse(id, mPrefs.getString(id, null));
    }

    public boolean isWatched(String id) {
        Entry entry = get(id);

        return entry != null && entry.isWatched();
    }

    /**
     * The "Continue watching" row, newest first. A film stays while it is unfinished. A series stays after a finished episode with the next
     * aired episode as its card ("Next: S01E02 ..."), and leaves when its last aired episode is finished or the viewer removes it.
     */
    public List<Row> continueRow(long now) {
        List<Entry> entries = new ArrayList<>();

        for (Map.Entry<String, ?> stored : mPrefs.getAll().entrySet()) {
            Entry entry = stored.getValue() instanceof String ? parse(stored.getKey(), (String) stored.getValue()) : null;

            if (entry != null) {
                entries.add(entry);
            }
        }

        Collections.sort(entries, (a, b) -> Long.compare(b.updatedAt, a.updatedAt));

        List<Row> result = new ArrayList<>();
        List<String> seen = new ArrayList<>();

        for (Entry entry : entries) {
            if (seen.contains(entry.titleId)) {
                continue;
            }

            seen.add(entry.titleId);

            if (entry.updatedAt <= mDismissed.getLong(entry.titleId, -1)) {
                continue;
            }

            boolean series = entry.season > 0;

            if (!entry.isWatched() && entry.positionMs >= MIN_RESUME_MS) {
                result.add(new Row(entry, series ? entry.season : 0, entry.episode, episodeTitle(entry, entry.season, entry.episode), false));
            } else if (series && entry.isWatched()) {
                UtubotFilmsCatalog.Episode next = nextAired(entry, now);

                if (next != null) {
                    result.add(new Row(entry, next.season, next.number, next.shortTitle(), true));
                }
            }
        }

        return result;
    }

    private String episodeTitle(Entry entry, int season, int number) {
        for (UtubotFilmsCatalog.Episode episode : episodesOf(entry.titleId)) {
            if (episode.season == season && episode.number == number) {
                return episode.shortTitle();
            }
        }

        return "";
    }

    @Nullable
    private UtubotFilmsCatalog.Episode nextAired(Entry finished, long now) {
        for (UtubotFilmsCatalog.Episode episode : episodesOf(finished.titleId)) {
            boolean after = episode.season > finished.season || (episode.season == finished.season && episode.number > finished.episode);

            if (after && episode.isAired(now)) {
                return episode;
            }
        }

        return null;
    }

    /** "40 min left" (rounded up to a whole minute), "1 h 5 min left"; empty for no time left */
    public static String timeLeft(long leftMs) {
        if (leftMs <= 0) {
            return "";
        }

        long minutes = (leftMs + MINUTE_MS - 1) / MINUTE_MS;

        if (minutes < HOUR_MINUTES) {
            return minutes + " min left";
        }

        long rest = minutes % HOUR_MINUTES;

        return minutes / HOUR_MINUTES + " h" + (rest > 0 ? " " + rest + " min" : "") + " left";
    }

    @Nullable
    private static Entry parse(String id, @Nullable String text) {
        if (text == null) {
            return null;
        }

        try {
            JSONObject json = new JSONObject(text);

            return new Entry(id, json.optString("type"), json.optString("titleId", id), json.optString("name"), json.optString("poster"),
                    json.optInt("season"), json.optInt("episode"), json.optLong("position"), json.optLong("duration"), json.optLong("updated"));
        } catch (JSONException e) {
            return null;
        }
    }
}
