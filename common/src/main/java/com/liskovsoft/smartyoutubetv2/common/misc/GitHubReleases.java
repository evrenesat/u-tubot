package com.liskovsoft.smartyoutubetv2.common.misc;

import android.content.Context;
import android.os.SystemClock;
import android.text.TextUtils;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.okhttp.OkHttpManager;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

import io.reactivex.Observable;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;

/**
 * The latest releases of the app on GitHub (Settings → Updates → Release notes), their notes rendered by GitHub itself:
 * the same HTML as the releases page, not markdown to render here.
 * When GitHub can't be reached, the changelog of the update channel (update.json) stands in for them.
 */
public final class GitHubReleases {
    /**
     * Of the API: the notes as HTML too (body_html)
     */
    private static final String ACCEPT = "application/vnd.github.html+json";
    private static final String API_VERSION = "2022-11-28";
    /**
     * Back and forth between the list and the notes doesn't ask again: the API allows 60 requests an hour without an account
     */
    private static final long CACHE_MS = 10 * 60 * 1_000;
    /**
     * Of the update channel's file: it is a few lines per version
     */
    private static final int MAX_UPDATE_JSON_BYTES = 256 * 1024;
    /**
     * Of update.json: the addresses of the packages, not a version
     */
    private static final String UPDATE_PACKAGE_KEY = "package";
    private static volatile Cached sCached;

    public static final class Release {
        /**
         * The tag, e.g. 32.68.3
         */
        public final String version;
        /**
         * Of the releases page, e.g. https://github.com/cygnusx-1-org/electriceel/releases/tag/32.68.3
         */
        public final String pageUrl;
        /**
         * The notes as GitHub renders them. Its addresses can be relative to github.com (e.g. the images of the repo).
         */
        public final String bodyHtml;
        /**
         * 0: not published yet
         */
        public final long publishedMs;

        public Release(String version, String pageUrl, String bodyHtml, long publishedMs) {
            this.version = version;
            this.pageUrl = pageUrl;
            this.bodyHtml = bodyHtml;
            this.publishedMs = publishedMs;
        }
    }

    private static final class Cached {
        final List<Release> releases;
        final long timeMs;

        Cached(List<Release> releases, long timeMs) {
            this.releases = releases;
            this.timeMs = timeMs;
        }
    }

    private GitHubReleases() {
    }

    /**
     * The newest first. Asked in the background, once in a while (see CACHE_MS).
     *
     * @param fallbackUrl the update.json of the update channel: its changelog is listed instead when GitHub fails.
     *                    Null or empty: the failure is the result.
     */
    public static Observable<List<Release>> latestObserve(Context context, @Nullable String fallbackUrl) {
        String url = context.getString(R.string.release_notes_url);
        String tagPrefix = context.getString(R.string.release_notes_tag_prefix);

        return RxHelper.fromCallable(() -> {
            Cached cached = sCached;
            // Not the wall clock: set back, it would keep an old list until the app restarts
            long nowMs = SystemClock.elapsedRealtime();

            if (cached != null && nowMs - cached.timeMs < CACHE_MS) {
                return cached.releases;
            }

            try {
                List<Release> releases = load(url, tagPrefix);
                sCached = new Cached(releases, nowMs);

                return releases;
            } catch (IOException e) {
                // Not cached: the next time GitHub is asked again
                return fallbackToUpdateChannel(fallbackUrl, e);
            }
        });
    }

    /**
     * What stands in for the releases when GitHub can't be reached: the changelog of the update channel, if there is one and it answers.
     * Otherwise GitHub's failure is the result.
     */
    static List<Release> fallbackToUpdateChannel(@Nullable String fallbackUrl, IOException githubError) throws IOException {
        if (TextUtils.isEmpty(fallbackUrl)) {
            throw githubError;
        }

        try {
            return loadUpdateChannel(fallbackUrl);
        } catch (IOException fallbackError) {
            throw githubError;
        }
    }

    /**
     * Whether the release is the installed one: its tag is the version name, with or without the prefix and a v
     * (e.g. utubot-v0.2.2 and 0.2.2 of the update channel are the version name 0.2.2)
     */
    public static boolean isInstalled(Release release, String versionName, String tagPrefix) {
        String tag = release.version.startsWith(tagPrefix) ? release.version.substring(tagPrefix.length()) : release.version;

        return !versionName.isEmpty() && withoutV(tag).equalsIgnoreCase(withoutV(versionName));
    }

    private static String withoutV(String version) {
        return version.startsWith("v") || version.startsWith("V") ? version.substring(1) : version;
    }

    static List<Release> load(String url, String tagPrefix) throws IOException {
        Request request = new Request.Builder()
                .url(url)
                .header("Accept", ACCEPT)
                .header("X-GitHub-Api-Version", API_VERSION)
                .build();

        try (Response response = OkHttpManager.instance().getClient().newCall(request).execute()) {
            ResponseBody body = response.body();

            if (!response.isSuccessful()) {
                throw new IOException("HTTP " + response.code());
            }

            return parse(body != null ? body.string() : "", tagPrefix);
        }
    }

    private static List<Release> loadUpdateChannel(String url) throws IOException {
        Request request = new Request.Builder().url(url).build();

        try (Response response = OkHttpManager.instance().getClient().newCall(request).execute()) {
            ResponseBody body = response.body();

            if (!response.isSuccessful() || body == null) {
                throw new IOException("HTTP " + response.code());
            }

            return parseUpdateChannel(readBounded(body.byteStream()));
        }
    }

    private static String readBounded(InputStream stream) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int read;

        while ((read = stream.read(buffer)) != -1) {
            bytes.write(buffer, 0, read);

            if (bytes.size() > MAX_UPDATE_JSON_BYTES) {
                throw new IOException("Too long");
            }
        }

        return bytes.toString(StandardCharsets.UTF_8.name());
    }

    /**
     * The versions of an update.json ({"package": {...}, "0.2.2": {"versionCode": 4, "changelog": ["a", "b"]}}), the newest
     * first, each with its changelog as a list. They have no date and no page of their own.
     */
    static List<Release> parseUpdateChannel(String json) throws IOException {
        try {
            JSONObject root = new JSONObject(json);
            List<String> versions = new ArrayList<>();

            for (Iterator<String> keys = root.keys(); keys.hasNext(); ) {
                String key = keys.next();

                if (!UPDATE_PACKAGE_KEY.equals(key) && root.optJSONObject(key) != null) {
                    versions.add(key);
                }
            }

            Collections.sort(versions, new Comparator<String>() {
                @Override
                public int compare(String left, String right) {
                    return compareVersions(right, left);
                }
            });

            List<Release> releases = new ArrayList<>();

            for (String version : versions) {
                releases.add(new Release(version, "", changelogHtml(root.getJSONObject(version)), 0));
            }

            return Collections.unmodifiableList(releases);
        } catch (JSONException e) {
            throw new IOException("Invalid response", e);
        }
    }

    private static String changelogHtml(JSONObject version) {
        List<String> lines = new ArrayList<>();
        JSONArray array = version.optJSONArray("changelog");

        if (array != null) {
            for (int i = 0; i < array.length(); i++) {
                lines.add(array.optString(i, ""));
            }
        } else {
            // A single text
            lines.add(getString(version, "changelog"));
        }

        StringBuilder html = new StringBuilder("<ul>");

        for (String line : lines) {
            if (!line.trim().isEmpty()) {
                html.append("<li>").append(TextUtils.htmlEncode(line.trim())).append("</li>");
            }
        }

        return html.append("</ul>").toString();
    }

    /**
     * Number by number (0.10.0 is after 0.9.0), what isn't a number is compared as text
     */
    static int compareVersions(String left, String right) {
        String[] leftParts = withoutV(left).split("[.\\-]");
        String[] rightParts = withoutV(right).split("[.\\-]");

        for (int i = 0; i < Math.max(leftParts.length, rightParts.length); i++) {
            String leftPart = i < leftParts.length ? leftParts[i] : "0";
            String rightPart = i < rightParts.length ? rightParts[i] : "0";
            int result;

            if (leftPart.matches("\\d{1,9}") && rightPart.matches("\\d{1,9}")) {
                result = Integer.compare(Integer.parseInt(leftPart), Integer.parseInt(rightPart));
            } else {
                result = leftPart.compareTo(rightPart);
            }

            if (result != 0) {
                return result;
            }
        }

        return 0;
    }

    /**
     * The drafts are left out: only an account that can edit the repo sees them
     *
     * @param tagPrefix only the releases whose tag starts with it are kept, e.g. utubot-v when the repo has releases of other
     *                  kinds too. Empty: all of them.
     */
    static List<Release> parse(String json, String tagPrefix) throws IOException {
        try {
            JSONArray items = new JSONArray(json);
            List<Release> releases = new ArrayList<>();

            for (int i = 0; i < items.length(); i++) {
                JSONObject item = items.optJSONObject(i);

                if (item == null || item.optBoolean("draft")) {
                    continue;
                }

                String version = getString(item, "tag_name");

                if (version.isEmpty() || !version.startsWith(tagPrefix)) {
                    continue;
                }

                releases.add(new Release(version, getString(item, "html_url"), getString(item, "body_html"),
                        parseDate(getString(item, "published_at"))));
            }

            return Collections.unmodifiableList(releases);
        } catch (JSONException e) {
            throw new IOException("Invalid response", e);
        }
    }

    /**
     * Empty when missing or null (e.g. the notes of a release without any): optString's is "null"
     */
    private static String getString(JSONObject item, String name) {
        return item.isNull(name) ? "" : item.optString(name, "");
    }

    /**
     * ISO 8601 in UTC, e.g. 2026-10-25T01:14:33Z
     */
    static long parseDate(String date) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));

        try {
            return format.parse(date).getTime();
        } catch (ParseException e) {
            return 0;
        }
    }
}
