package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * A Stremio stream addon (Torrentio, or a self-hosted Comet/MediaFusion) for the Real-Debrid spike: ask it for the streams of an IMDb id
 * ({@link #streams}) and, for a Real-Debrid stream, build the address the player reads. The addon is a plain Stremio addon, so no u·tubot
 * backend is involved; the Real-Debrid token (owner-entered on the TV, never committed) rides here and is added to a stream's address when
 * the stream needs it, never to the addon call or to a log.
 *
 * <p>A Stremio addon answers the streams of a title at {@code POST {addonUrl}/Streams/{imdbId}} with {@code {"Streams": [...]}}. Each entry
 * has a {@code name}, and either a direct {@code url} (a Real-Debrid link, or a {@code bd:<hash>} the Real-Debrid API resolves) or an
 * {@code infoHash}/{@code hash} for a torrent the Real-Debrid API has to resolve first.
 */
public class UtubotRealDebridClient {
    private static final int TIMEOUT_MS = 30_000;
    private static final String BD_PREFIX = "bd:";

    private final String mAddonUrl;
    @Nullable
    private final String mRealDebridToken;

    public UtubotRealDebridClient(String addonUrl, @Nullable String realDebridToken) {
        mAddonUrl = stripTrailingSlash(addonUrl == null ? "" : addonUrl.trim());
        mRealDebridToken = realDebridToken == null ? "" : realDebridToken.trim();
    }

    /**
     * The addon's streams for one title. The addon address is the caller's (Torrentio, Comet, MediaFusion); the Real-Debrid token is not
     * sent here, it is added to a stream's address when the stream needs it (see {@link Stream#playbackUrl}).
     *
     * @throws IOException the addon did not answer or answered with a non-2xx status or a body that holds no streams
     */
    public List<Stream> streams(String imdbId) throws IOException {
        if (mAddonUrl.isEmpty() || imdbId == null || imdbId.isEmpty()) {
            throw new IOException("A stream addon address and an IMDb id are needed");
        }

        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .readTimeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .build();

        Request request = new Request.Builder()
                .url(mAddonUrl + "/Streams/" + imdbId.trim())
                .post(RequestBody.create(new byte[0], null))
                .build();

        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new IOException("Addon returned HTTP " + response.code());
            }

            String body = response.body() != null ? response.body().string() : "";
            return parseStreams(body);
        } catch (JSONException e) {
            throw new IOException("Bad addon answer: " + e.getMessage(), e);
        }
    }

    /**
     * The streams of a Stremio addon answer (a {@code {"Streams": [...]}} object, or a bare array). Entries without any address or hash
     * are dropped: nothing to play.
     */
    static List<Stream> parseStreams(String body) throws JSONException {
        List<Stream> result = new ArrayList<>();

        if (body == null || body.trim().isEmpty()) {
            return result;
        }

        JSONArray array;

        try {
            array = new JSONArray(body.trim()); // a bare array, no wrapper object
        } catch (JSONException notAnArray) {
            JSONObject root = new JSONObject(body);
            array = root.optJSONArray("Streams");

            if (array == null) {
                array = root.optJSONArray("streams");
            }
        }

        if (array == null) {
            throw new JSONException("No Streams array");
        }

        for (int i = 0; i < array.length(); i++) {
            JSONObject entry = array.getJSONObject(i);
            Stream stream = parseStream(entry);

            if (stream != null) {
                result.add(stream);
            }
        }

        return result;
    }

    @Nullable
    private static Stream parseStream(JSONObject entry) throws JSONException {
        String name = entry.optString("name", entry.optString("Name", null));
        String url = entry.optString("url", entry.optString("Url", null));
        String infoHash = entry.optString("infoHash", entry.optString("info_hash",
                entry.optString("InfoHash", null)));

        if (infoHash == null) {
            infoHash = entry.optString("hash", null);
        }

        if (isBlank(url) && isBlank(infoHash)) {
            // A stream with neither a direct address nor a torrent hash cannot be played.
            return null;
        }

        int resolution = parseResolution(name, entry);
        long sizeBytes = parseSize(entry);
        boolean isRealDebrid = name != null && name.toLowerCase().contains("debrid");

        return new Stream(name, url, infoHash, resolution, sizeBytes, isRealDebrid);
    }

    /**
     * The address the player reads. A direct HTTP(S) URL plays as is; a Real-Debrid {@code bd:<hash>} link, or any stream flagged as
     * Real-Debrid, gets the token added so the Real-Debrid CDN serves it. A stream without a token cannot be played: the caller shows it
     * as locked.
     */
    @Nullable
    public String playbackUrl(Stream stream) {
        if (stream == null) {
            return null;
        }

        String url = stream.url;

        if (isBlank(url)) {
            return null;
        }

        boolean isRealDebrid = url.startsWith(BD_PREFIX) || stream.isRealDebrid;

        if (!isRealDebrid || mRealDebridToken.isEmpty()) {
            return isBlank(url) ? null : url;
        }

        return applyToken(url, mRealDebridToken);
    }

    /**
     * A Real-Debrid link carries the token as a query parameter; a direct URL that already is one is left as is.
     */
    static String applyToken(String url, String token) {
        String separator = url.indexOf('?') < 0 ? "?" : "&";
        return url + separator + "token=" + token;
    }

    private static int parseResolution(String name, JSONObject entry) throws JSONException {
        JSONArray resolutions = entry.optJSONObject("behaviorHints") != null
                ? entry.optJSONObject("behaviorHints").optJSONArray("resolutions") : null;

        if (resolutions != null && resolutions.length() > 0) {
            int best = 0;

            for (int i = 0; i < resolutions.length(); i++) {
                String resolution = resolutions.optString(i, "");
                int pixels = resolutionPixels(resolution);
                if (pixels > best) {
                    best = pixels;
                }
            }

            if (best > 0) {
                return best;
            }
        }

        String infoResolution = entry.optJSONObject("info") != null ? entry.optJSONObject("info").optString("resolution", "") : "";
        int fromInfo = resolutionPixels(infoResolution);
        if (fromInfo > 0) {
            return fromInfo;
        }

        return resolutionPixels(name);
    }

    private static int resolutionPixels(String text) {
        if (isBlank(text)) {
            return 0;
        }

        String lower = text.toLowerCase();

        if (lower.contains("2160") || lower.contains("4k") || lower.contains("2k")) {
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

    private static long parseSize(JSONObject entry) throws JSONException {
        JSONObject info = entry.optJSONObject("info");

        if (info != null) {
            long bytes = info.optLong("bytes", 0);

            if (bytes > 0) {
                return bytes;
            }
        }

        return 0;
    }

    private static boolean isBlank(String text) {
        return text == null || text.trim().isEmpty();
    }

    private static String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    /**
     * One stream of a Stremio addon answer.
     *
     * @param name       the display name (title, codec, quality), or null
     * @param url        a direct address (a Real-Debrid link or an HTTP file), or null for a torrent-only stream
     * @param infoHash   the torrent hash, or null when there is none
     * @param resolution the height in pixels (2160, 1080, 720, 480), 0 when unknown
     * @param sizeBytes  the file size in bytes, 0 when unknown
     * @param isRealDebrid the entry was flagged as a Real-Debrid stream (its name says so, or it is a {@code bd:} link)
     */
    public static final class Stream {
        public final String name;
        public final String url;
        public final String infoHash;
        public final int resolution;
        public final long sizeBytes;
        public final boolean isRealDebrid;

        public Stream(String name, String url, String infoHash, int resolution, long sizeBytes) {
            this(name, url, infoHash, resolution, sizeBytes, false);
        }

        public Stream(String name, String url, String infoHash, int resolution, long sizeBytes, boolean isRealDebrid) {
            this.name = name;
            this.url = url;
            this.infoHash = infoHash;
            this.resolution = resolution;
            this.sizeBytes = sizeBytes;
            this.isRealDebrid = isRealDebrid || (url != null && url.startsWith(BD_PREFIX));
        }

        /**
         * A stream the player can open now: either a direct HTTP(S) address, or a Real-Debrid {@code bd:} link the Real-Debrid API
         * resolves (with the token). A torrent-only entry (a hash, no address) is not directly playable.
         */
        public boolean isDirectPlayable() {
            return !isBlank(url);
        }

        @Nullable
        public String display() {
            StringBuilder text = new StringBuilder();

            if (!isBlank(name)) {
                text.append(name);
            }

            if (resolution > 0) {
                if (text.length() > 0) {
                    text.append("  ");
                }

                text.append('[').append(resolution).append('p');

                if (sizeBytes > 0) {
                    text.append(", ").append(formatSize(sizeBytes));
                }

                text.append(']');
            }

            return text.length() == 0 ? "(unnamed stream)" : text.toString();
        }

        private static String formatSize(long bytes) {
            if (bytes < 1024) {
                return bytes + " B";
            } else if (bytes < 1024 * 1024) {
                return String.format("%.1f KB", bytes / 1024.0);
            } else if (bytes < 1024 * 1024 * 1024) {
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
