package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

/**
 * A Stremio stream addon (Torrentio, or a self-hosted Comet/MediaFusion) for the Real-Debrid spike: ask it for the streams of an IMDb id
 * ({@link #streams}). No u·tubot backend is involved.
 *
 * <p>The addon answers {@code GET {addonUrl}/stream/movie/{imdbId}.json} with {@code {"streams": [...]}}. With a debrid service configured in
 * the addon, each entry carries a direct {@code url} the player reads as is. The addon address may hold the Real-Debrid key itself (Torrentio:
 * {@code https://host/realdebrid=KEY}); to keep the key out of the address that is shown and stored, the address may hold the placeholder
 * {@value #TOKEN_PLACEHOLDER}, which is replaced by the token entered on the TV. Neither the address nor the token is ever logged or put into an
 * error message.
 */
public class UtubotRealDebridClient {
    public static final String TYPE_MOVIE = "movie";
    public static final String TYPE_SERIES = "series";
    public static final String TOKEN_PLACEHOLDER = "{token}";
    private static final int TIMEOUT_MS = 30_000;
    private static final String STREAM_SUFFIX = ".json";

    private final String mAddonUrl;

    public UtubotRealDebridClient(String addonUrl, @Nullable String realDebridToken) {
        String url = addonUrl == null ? "" : addonUrl.trim();
        String token = realDebridToken == null ? "" : realDebridToken.trim();
        mAddonUrl = stripTrailingSlash(url.replace(TOKEN_PLACEHOLDER, token));
    }

    /**
     * The addon's streams for one title.
     *
     * @throws IOException the addon did not answer, answered with a non-2xx status or an unreadable body; the message never holds the address
     */
    public List<Stream> streams(String imdbId) throws IOException {
        return streams(TYPE_MOVIE, imdbId);
    }

    /**
     * The addon's streams for a movie, or for one episode of a series (id {@code tt0000000:season:episode}).
     */
    public List<Stream> streams(String type, String imdbId) throws IOException {
        if (mAddonUrl.isEmpty() || imdbId == null || imdbId.trim().isEmpty()) {
            throw new IOException("A stream addon address and an IMDb id are needed");
        }

        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .readTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .build();

        Request request;

        try {
            request = new Request.Builder().url(mAddonUrl + "/stream/" + type + "/" + imdbId.trim() + STREAM_SUFFIX).get().build();
        } catch (IllegalArgumentException e) {
            throw new IOException("The stream addon address is not a valid web address");
        }

        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new IOException("Addon returned HTTP " + response.code());
            }

            return parseStreams(response.body() != null ? response.body().string() : "");
        } catch (JSONException e) {
            throw new IOException("The addon answer is not a stream list");
        } catch (IOException e) {
            // Transport errors can quote the request address, which may hold the key: say only the kind of failure.
            if (e.getMessage() != null && e.getMessage().startsWith("Addon returned")) {
                throw e;
            }

            throw new IOException("The addon could not be reached (" + e.getClass().getSimpleName() + ")");
        }
    }

    /**
     * The streams of a Stremio addon answer ({@code {"streams": [...]}}, or a bare array). Entries without a direct address are dropped: a
     * torrent-only entry is not playable without a debrid service.
     */
    static List<Stream> parseStreams(String body) throws JSONException {
        List<Stream> result = new ArrayList<>();

        if (body == null || body.trim().isEmpty()) {
            return result;
        }

        String text = body.trim();
        JSONArray array;

        if (text.startsWith("[")) {
            array = new JSONArray(text);
        } else {
            array = new JSONObject(text).optJSONArray("streams");

            if (array == null) {
                throw new JSONException("No streams array");
            }
        }

        for (int i = 0; i < array.length(); i++) {
            Stream stream = parseStream(array.getJSONObject(i));

            if (stream != null) {
                result.add(stream);
            }
        }

        return result;
    }

    @Nullable
    private static Stream parseStream(JSONObject entry) {
        String url = entry.optString("url", "");

        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return null;
        }

        String name = entry.optString("name", "");
        String title = entry.optString("title", "");
        String label = name.isEmpty() ? title : title.isEmpty() ? name : name + " " + title;
        JSONObject hints = entry.optJSONObject("behaviorHints");
        long sizeBytes = hints != null ? hints.optLong("videoSize", 0) : 0;

        return new Stream(label.replace('\n', ' '), url, resolutionPixels(label), sizeBytes);
    }

    private static int resolutionPixels(String text) {
        String lower = text.toLowerCase();

        if (lower.contains("2160") || lower.contains("4k")) {
            return 2160;
        }

        if (lower.contains("1080")) {
            return 1080;
        }

        if (lower.contains("720")) {
            return 720;
        }

        if (lower.contains("480")) {
            return 480;
        }

        return 0;
    }

    /**
     * The streams in the order of the list on this TV: those it shows in colour first, then by height and size, so the best stream is first.
     * Streams it cannot show in colour come last. The input list is not changed.
     */
    public static List<Stream> sortedFor(List<Stream> streams, UtubotFilmFormat.Device device) {
        List<Stream> sorted = new ArrayList<>(streams);

        Collections.sort(sorted, (a, b) -> {
            int verdict = a.format.verdict(device).compareTo(b.format.verdict(device));

            if (verdict != 0) {
                return verdict;
            }

            int resolution = Integer.compare(b.resolution, a.resolution);

            return resolution != 0 ? resolution : Long.compare(b.sizeBytes, a.sizeBytes);
        });

        return sorted;
    }

    private static String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    /**
     * One playable stream of a Stremio addon answer.
     *
     * @param name       the display text (name and title: quality, codec, size), possibly empty
     * @param url        the direct address the player reads; it may carry a key, so it is never shown or logged
     * @param resolution the height in pixels (2160, 1080, 720, 480), 0 when unknown
     * @param sizeBytes  the file size in bytes, 0 when unknown
     */
    public static final class Stream {
        public final String name;
        public final String url;
        public final int resolution;
        public final long sizeBytes;
        /** What the name says about the picture and sound */
        public final UtubotFilmFormat format;

        public Stream(String name, String url, int resolution, long sizeBytes) {
            this.name = name;
            this.url = url;
            this.resolution = resolution;
            this.sizeBytes = sizeBytes;
            this.format = UtubotFilmFormat.parse(name);
        }

        public String display() {
            StringBuilder text = new StringBuilder(name == null ? "" : name);

            if (sizeBytes > 0) {
                text.append(text.length() > 0 ? "  [" : "[").append(formatSize(sizeBytes)).append(']');
            }

            return text.length() == 0 ? "(unnamed stream)" : text.toString();
        }

        public static String formatSize(long bytes) {
            if (bytes < 1024L * 1024L) {
                return String.format("%.1f KB", bytes / 1024.0);
            } else if (bytes < 1024L * 1024L * 1024L) {
                return String.format("%.1f MB", bytes / (1024.0 * 1024.0));
            }

            return String.format("%.1f GB", bytes / (1024.0 * 1024.0 * 1024.0));
        }

        @Override
        public String toString() {
            return display();
        }
    }
}
