package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import okhttp3.ConnectionPool;
import okhttp3.Dns;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * The u·tubot backend's Stremio library endpoints for the films watch: whether the owner's Stremio
 * account is connected ({@link #status}) and, on demand, the mapped library ({@link #importLibrary}).
 * The Stremio auth key never passes through here: the server logs in with it, imports on the
 * owner's behalf, and returns only the mapped titles.
 */
public class UtubotStremioClient {
    public static final String TYPE_MOVIE = "movie";
    public static final String TYPE_SERIES = "series";
    private static final String API_PREFIX = "/v1/films/stremio";
    private static final int TIMEOUT_MS = 20_000;
    private static final int POOL_MAX_IDLE = 5;
    private static final int POOL_KEEP_ALIVE_SEC = 30;

    private final String mBaseUrl;
    private final String mToken;

    public UtubotStremioClient(@Nullable String baseUrl, @Nullable String token) {
        mBaseUrl = stripTrailingSlash(normalize(baseUrl));
        mToken = normalize(token);
    }

    /** Whether the owner's Stremio account is connected on the backend */
    public boolean status() throws IOException {
        return parseStatus(get("/status"));
    }

    /** The mapped library and the counts */
    public ImportResult importLibrary() throws IOException {
        return parseImport(post("/import"));
    }

    private OkHttpClient client() {
        return new OkHttpClient.Builder()
                .proxy(Proxy.NO_PROXY)
                .dns(Dns.SYSTEM)
                .connectTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .readTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .retryOnConnectionFailure(false)
                .connectionPool(new ConnectionPool(POOL_MAX_IDLE, POOL_KEEP_ALIVE_SEC, TimeUnit.SECONDS))
                .build();
    }

    private String path(String suffix) {
        return mBaseUrl + API_PREFIX + suffix;
    }

    private String get(String suffix) throws IOException {
        Request request;

        try {
            request = new Request.Builder().url(path(suffix)).get().build();
        } catch (IllegalArgumentException e) {
            throw new IOException("The backend address is not a valid web address");
        }

        return send(request);
    }

    private String post(String suffix) throws IOException {
        Request request;

        try {
            request = new Request.Builder().url(path(suffix)).post(RequestBody.create(new byte[0], null)).build();
        } catch (IllegalArgumentException e) {
            throw new IOException("The backend address is not a valid web address");
        }

        return send(request);
    }

    private String send(Request request) throws IOException {
        try (Response response = client().newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new IOException("The backend returned HTTP " + response.code());
            }

            return response.body() != null ? response.body().string() : "{}";
        } catch (IOException e) {
            // Transport errors quote the request address, which is the backend: say only the kind of failure.
            if (e.getMessage() != null && e.getMessage().startsWith("The backend returned")) {
                throw e;
            }

            throw new IOException("The backend could not be reached (" + e.getClass().getSimpleName() + ")");
        }
    }

    private boolean parseStatus(String body) throws IOException {
        try {
            return new JSONObject(body).optBoolean("set", false);
        } catch (JSONException e) {
            throw new IOException("The backend answer is not readable");
        }
    }

    private ImportResult parseImport(String body) throws IOException {
        List<ImportedItem> items = new ArrayList<>();

        try {
            JSONObject root = new JSONObject(body);
            JSONArray list = root.optJSONArray("items");

            if (list != null) {
                for (int i = 0; i < list.length(); i++) {
                    items.add(parseItem(list.getJSONObject(i)));
                }
            }

            return new ImportResult(root.optInt("watchlist", 0), root.optInt("resume", 0),
                    root.optInt("watched", 0), root.optInt("unmapped", 0), items);
        } catch (JSONException e) {
            throw new IOException("The backend answer is not readable");
        }
    }

    private ImportedItem parseItem(JSONObject item) {
        return new ImportedItem(item.optString("id", ""), item.optString("type", TYPE_MOVIE),
                item.optString("title_id", item.optString("id", "")), item.optString("name", ""),
                item.optString("poster", ""), item.optInt("season", 0), item.optInt("episode", 0),
                item.optLong("position_ms", 0), item.optBoolean("watched", false),
                item.optLong("last_watched", 0));
    }

    private static String normalize(@Nullable String value) {
        return value == null ? "" : value.trim();
    }

    private static String stripTrailingSlash(String value) {
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    /** The mapped library and the counts returned by the import */
    public static final class ImportResult {
        /** The number of mapped titles (the watchlist) */
        public final int watchlistCount;
        /** The mapped titles with a resume position */
        public final int resumeCount;
        /** The mapped titles marked watched */
        public final int watchedCount;
        /** The library titles that could not be mapped to an IMDb id */
        public final int unmappedCount;
        public final List<ImportedItem> items;

        public ImportResult(int watchlistCount, int resumeCount, int watchedCount, int unmappedCount,
                            List<ImportedItem> items) {
            this.watchlistCount = watchlistCount;
            this.resumeCount = resumeCount;
            this.watchedCount = watchedCount;
            this.unmappedCount = unmappedCount;
            this.items = items;
        }
    }

    /** One mapped item of the owner's Stremio library, ready for the films store */
    public static final class ImportedItem {
        public final String id;
        public final String type;
        public final String titleId;
        public final String name;
        public final String poster;
        public final int season;
        public final int episode;
        public final long positionMs;
        public final boolean watched;
        public final long lastWatched;

        public ImportedItem(String id, String type, String titleId, String name, String poster, int season,
                            int episode, long positionMs, boolean watched, long lastWatched) {
            this.id = id;
            this.type = type;
            this.titleId = titleId;
            this.name = name;
            this.poster = poster;
            this.season = season;
            this.episode = episode;
            this.positionMs = positionMs;
            this.watched = watched;
            this.lastWatched = lastWatched;
        }

        /** A title-level item: a movie, or the series-level resume of a series (season 0, episode 0) */
        public boolean isTitleLevel() {
            return season == 0 && episode == 0;
        }
    }
}
