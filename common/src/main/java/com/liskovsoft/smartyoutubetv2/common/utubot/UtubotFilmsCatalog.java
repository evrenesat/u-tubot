package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

/**
 * The titles the films screens browse: a Stremio catalogue addon (Cinemeta by default) answers lists ({@code /catalog/{type}/{id}.json}), a
 * search ({@code /catalog/{type}/top/search={text}.json}) and the details of one title ({@code /meta/{type}/{id}.json}). No stream address
 * or key passes through here.
 */
public class UtubotFilmsCatalog {
    public static final String DEFAULT_URL = "https://v3-cinemeta.strem.io";
    public static final String POPULAR = "top";
    public static final String TRENDING = "year";
    private static final int TIMEOUT_MS = 20_000;

    private final String mBaseUrl;

    public UtubotFilmsCatalog(@Nullable String baseUrl) {
        String url = baseUrl == null ? "" : baseUrl.trim();
        mBaseUrl = url.isEmpty() ? DEFAULT_URL : url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    /** One title of a list */
    public static final class Item {
        public final String type;
        public final String id;
        public final String name;
        public final String year;
        public final String poster;
        public final String background;
        public final String rating;
        public final String runtime;
        public final String plot;
        public final List<Episode> episodes;

        public Item(String type, String id, String name, String year, String poster, String background, String rating, String runtime, String plot,
                    List<Episode> episodes) {
            this.type = type;
            this.id = id;
            this.name = name;
            this.year = year;
            this.poster = poster;
            this.background = background;
            this.rating = rating;
            this.runtime = runtime;
            this.plot = plot;
            this.episodes = episodes;
        }

        public boolean isSeries() {
            return UtubotRealDebridClient.TYPE_SERIES.equals(type);
        }

        /** The line under the title: year, runtime, rating */
        public String facts() {
            StringBuilder text = new StringBuilder();
            append(text, year);
            append(text, runtime);
            append(text, rating.isEmpty() ? "" : "IMDb " + rating);

            return text.toString();
        }

        private static void append(StringBuilder text, String part) {
            if (!part.isEmpty()) {
                text.append(text.length() > 0 ? "  |  " : "").append(part);
            }
        }
    }

    /** One episode of a series */
    public static final class Episode {
        public final int season;
        public final int number;
        public final String title;
        /** When it first aired (epoch ms), 0 when the catalogue does not say */
        public final long releasedMs;

        public Episode(int season, int number, String title) {
            this(season, number, title, 0);
        }

        public Episode(int season, int number, String title, long releasedMs) {
            this.season = season;
            this.number = number;
            this.title = title;
            this.releasedMs = releasedMs;
        }

        /** An episode with no known air date counts as aired */
        public boolean isAired(long now) {
            return releasedMs <= 0 || releasedMs <= now;
        }

        /** The title without a leading "Episode N:" (the card already says "EN"); empty when nothing else is left */
        public String shortTitle() {
            String text = title == null ? "" : title.replaceFirst("(?i)^\\s*episode\\s*\\d+\\s*[:.\\-\u2013]?\\s*", "").trim();

            return text;
        }

        /** The Stremio id of the episode's streams, e.g. tt0944947:1:2 */
        public String videoId(String seriesId) {
            return seriesId + ":" + season + ":" + number;
        }
    }

    public List<Item> list(String type, String catalog) throws IOException {
        return parseList(get("/catalog/" + type + "/" + catalog + ".json"), type);
    }

    public List<Item> search(String type, String text) throws IOException {
        return parseList(get("/catalog/" + type + "/top/search=" + URLEncoder.encode(text.trim(), "UTF-8").replace("+", "%20") + ".json"), type);
    }

    public Item meta(String type, String id) throws IOException {
        try {
            JSONObject meta = new JSONObject(get("/meta/" + type + "/" + id + ".json")).optJSONObject("meta");

            if (meta == null) {
                throw new IOException("The catalogue has no such title");
            }

            return parseItem(meta, type);
        } catch (JSONException e) {
            throw new IOException("The catalogue answer is not readable");
        }
    }

    private String get(String path) throws IOException {
        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .readTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .build();

        Request request;

        try {
            request = new Request.Builder().url(mBaseUrl + path).get().build();
        } catch (IllegalArgumentException e) {
            throw new IOException("The catalogue address is not a valid web address");
        }

        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new IOException("The catalogue returned HTTP " + response.code());
            }

            return response.body() != null ? response.body().string() : "";
        }
    }

    static List<Item> parseList(String body, String type) throws IOException {
        List<Item> items = new ArrayList<>();

        try {
            JSONArray metas = new JSONObject(body).optJSONArray("metas");

            for (int i = 0; metas != null && i < metas.length(); i++) {
                Item item = parseItem(metas.getJSONObject(i), type);

                if (!item.id.isEmpty() && !item.name.isEmpty()) {
                    items.add(item);
                }
            }
        } catch (JSONException e) {
            throw new IOException("The catalogue answer is not readable");
        }

        return items;
    }

    static Item parseItem(JSONObject meta, String fallbackType) {
        String year = meta.optString("year", "");

        if (year.isEmpty()) {
            year = meta.optString("releaseInfo", "");
        }

        List<Episode> episodes = new ArrayList<>();
        JSONArray videos = meta.optJSONArray("videos");

        for (int i = 0; videos != null && i < videos.length(); i++) {
            JSONObject video = videos.optJSONObject(i);
            int season = video == null ? 0 : video.optInt("season", 0);
            int number = video == null ? 0 : video.optInt("episode", video.optInt("number", 0));

            if (season > 0 && number > 0) {
                episodes.add(new Episode(season, number, video.optString("title", video.optString("name", "")),
                        parseDate(video.optString("released", ""))));
            }
        }

        return new Item(meta.optString("type", fallbackType), meta.optString("id", ""), meta.optString("name", ""), year,
                meta.optString("poster", ""), meta.optString("background", ""), meta.optString("imdbRating", ""),
                runtime(meta.optString("runtime", "")), meta.optString("description", ""), episodes);
    }

    /** An ISO date or date-time ("2026-03-01", "2026-03-01T00:00:00.000Z") in epoch ms, 0 when it is missing or unreadable */
    static long parseDate(@Nullable String text) {
        if (text == null || text.length() < 10) {
            return 0;
        }

        try {
            java.text.SimpleDateFormat format = new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US);
            format.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));

            return format.parse(text.substring(0, 10)).getTime();
        } catch (java.text.ParseException e) {
            return 0;
        }
    }

    /** "148 min" or "2h 28min" as the catalogue gives it, kept as is; empty when unknown */
    private static String runtime(String text) {
        return text == null ? "" : text.trim();
    }

    /** The runtime of {@link #runtime} in milliseconds: "148 min", "2h 28min" and a bare "148" work, 0 when it says nothing readable */
    public static long runtimeMs(@Nullable String text) {
        if (text == null) {
            return 0;
        }

        long hours = firstNumber(text, "(\\d+)\\s*h");
        long minutes = firstNumber(text, "(\\d+)\\s*m");

        if (hours == 0 && minutes == 0) {
            minutes = firstNumber(text, "^\\s*(\\d+)\\s*$");
        }

        return TimeUnit.HOURS.toMillis(hours) + TimeUnit.MINUTES.toMillis(minutes);
    }

    private static long firstNumber(String text, String pattern) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile(pattern).matcher(text);

        return matcher.find() ? Long.parseLong(matcher.group(1)) : 0;
    }

    /** The seasons of an episode list, in order and without repeats */
    public static List<Integer> seasons(List<Episode> episodes) {
        List<Integer> seasons = new ArrayList<>();

        for (Episode episode : episodes) {
            if (!seasons.contains(episode.season)) {
                seasons.add(episode.season);
            }
        }

        java.util.Collections.sort(seasons);

        return seasons;
    }

    public static List<Episode> episodesOf(List<Episode> episodes, int season) {
        List<Episode> result = new ArrayList<>();

        for (Episode episode : episodes) {
            if (episode.season == season) {
                result.add(episode);
            }
        }

        java.util.Collections.sort(result, (a, b) -> Integer.compare(a.number, b.number));

        return result;
    }
}
