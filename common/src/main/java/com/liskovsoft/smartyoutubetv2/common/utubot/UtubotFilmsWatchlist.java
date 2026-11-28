package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The owner's Stremio library as imported on this TV: the titles (the "My list" row), the resume
 * positions (feeding "Continue watching"), and the watched marks. The Stremio auth key never
 * reaches here; the backend imports on the owner's behalf and returns only the mapped titles. One
 * JSON blob, replaced whole on each import.
 */
public class UtubotFilmsWatchlist {
    private static final String PREFS = "utubot_films_watchlist";

    private final SharedPreferences mPrefs;

    public UtubotFilmsWatchlist(Context context) {
        mPrefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Replace the imported library with the mapped items */
    public void apply(List<UtubotStremioClient.ImportedItem> items) {
        try {
            JSONArray json = new JSONArray();

            for (UtubotStremioClient.ImportedItem item : items) {
                json.put(new JSONObject()
                        .put("id", item.id)
                        .put("type", item.type)
                        .put("titleId", item.titleId)
                        .put("name", item.name)
                        .put("poster", item.poster == null ? "" : item.poster)
                        .put("season", item.season)
                        .put("episode", item.episode)
                        .put("position", item.positionMs)
                        .put("watched", item.watched)
                        .put("lastWatched", item.lastWatched));
            }

            mPrefs.edit().putString("items", json.toString()).apply();
        } catch (JSONException e) {
            // an item with unusable text is not remembered
        }
    }

    /** All imported items, in the order the backend returned them */
    public List<UtubotStremioClient.ImportedItem> all() {
        List<UtubotStremioClient.ImportedItem> items = new ArrayList<>();
        String text = mPrefs.getString("items", null);

        if (text == null) {
            return items;
        }

        try {
            JSONArray array = new JSONArray(text);

            for (int i = 0; i < array.length(); i++) {
                JSONObject item = array.getJSONObject(i);
                items.add(new UtubotStremioClient.ImportedItem(item.optString("id", ""),
                        item.optString("type", UtubotStremioClient.TYPE_MOVIE),
                        item.optString("titleId", item.optString("id", "")), item.optString("name", ""),
                        item.optString("poster", ""), item.optInt("season", 0), item.optInt("episode", 0),
                        item.optLong("position", 0), item.optBoolean("watched", false),
                        item.optLong("lastWatched", 0)));
            }
        } catch (JSONException e) {
            // an unreadable store is treated as empty
        }

        return items;
    }

    /** The distinct titles for the "My list" row: one per title id, the title-level item when there is one */
    public List<UtubotStremioClient.ImportedItem> titles() {
        Map<String, UtubotStremioClient.ImportedItem> byTitle = new LinkedHashMap<>();

        for (UtubotStremioClient.ImportedItem item : all()) {
            UtubotStremioClient.ImportedItem current = byTitle.get(item.titleId);

            if (current == null || (item.isTitleLevel() && !current.isTitleLevel())) {
                byTitle.put(item.titleId, item);
            }
        }

        return new ArrayList<>(byTitle.values());
    }

    /** The resume positions for the "Continue watching" row, newest first, one per title id */
    public List<UtubotStremioClient.ImportedItem> resume() {
        List<UtubotStremioClient.ImportedItem> byTitle = new ArrayList<>();
        Map<String, UtubotStremioClient.ImportedItem> seen = new LinkedHashMap<>();

        for (UtubotStremioClient.ImportedItem item : all()) {
            if (!item.watched && item.positionMs >= UtubotFilmsProgress.MIN_RESUME_MS && !seen.containsKey(item.titleId)) {
                seen.put(item.titleId, item);
                byTitle.add(item);
            }
        }

        Collections.sort(byTitle, (a, b) -> Long.compare(b.lastWatched, a.lastWatched));

        return byTitle;
    }

    /** Whether one id is a watched mark */
    public boolean isWatched(String id) {
        for (UtubotStremioClient.ImportedItem item : all()) {
            if (item.watched && item.id.equals(id)) {
                return true;
            }
        }

        return false;
    }

    /** The number of imported items, 0 when nothing has been imported yet */
    public int size() {
        return all().size();
    }
}
