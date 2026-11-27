package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.Nullable;

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

        public float share() {
            return durationMs <= 0 ? 0f : Math.min(1f, positionMs / (float) durationMs);
        }
    }

    private final SharedPreferences mPrefs;

    public UtubotFilmsProgress(Context context) {
        mPrefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
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
     * The "Continue watching" row: unfinished titles, newest first; an unfinished series shows its latest episode only.
     */
    public List<Entry> continueWatching() {
        List<Entry> entries = new ArrayList<>();

        for (Map.Entry<String, ?> stored : mPrefs.getAll().entrySet()) {
            Entry entry = stored.getValue() instanceof String ? parse(stored.getKey(), (String) stored.getValue()) : null;

            if (entry != null && !entry.isWatched() && entry.positionMs >= MIN_RESUME_MS) {
                entries.add(entry);
            }
        }

        Collections.sort(entries, (a, b) -> Long.compare(b.updatedAt, a.updatedAt));

        List<Entry> result = new ArrayList<>();
        List<String> seen = new ArrayList<>();

        for (Entry entry : entries) {
            if (!seen.contains(entry.titleId)) {
                seen.add(entry.titleId);
                result.add(entry);
            }
        }

        return result;
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
