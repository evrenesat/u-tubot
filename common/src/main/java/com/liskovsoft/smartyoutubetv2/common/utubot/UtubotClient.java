package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.net.Proxy;
import java.util.List;
import java.util.concurrent.TimeUnit;

import okhttp3.Dns;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * Blocking calls to the u-tubot backend (ai/CONTRACT.md). Its own OkHttp client: the system's DNS and no proxy, as the backend is the
 * user's own (a LAN address or a tailnet name), and none of the YouTube client's headers or cookies.
 */
public class UtubotClient {
    public static final String API_PREFIX = "/v1";
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final int CONNECT_TIMEOUT_SEC = 5;
    private static final int WRITE_TIMEOUT_SEC = 10;
    private static final int LONG_POLL_SLACK_MS = 10_000;
    private static final int IMPORT_TIMEOUT_MS = 30_000;
    private static final int MAX_ERROR_CHARS = 120;
    private static final int CHUNK_BYTES = 4096;
    private static final long MAX_SETUP_BYTES = 64 * 1024;
    private static final int DEFAULT_READ_TIMEOUT_SEC = 15;
    private static final int HTTP_UNAUTHORIZED = 401;
    private static final int MAX_ASSESS_VIDEOS = 50;
    private static final OkHttpClient sBase = new OkHttpClient.Builder()
            .proxy(Proxy.NO_PROXY)
            .dns(Dns.SYSTEM)
            .connectTimeout(CONNECT_TIMEOUT_SEC, TimeUnit.SECONDS)
            .writeTimeout(WRITE_TIMEOUT_SEC, TimeUnit.SECONDS)
            .readTimeout(DEFAULT_READ_TIMEOUT_SEC, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build();

    /**
     * The backend answered with an error status
     */
    public static class HttpException extends IOException {
        public final int code;

        public HttpException(int code, String message) {
            super(message);
            this.code = code;
        }

        public boolean isUnauthorized() {
            return code == HTTP_UNAUTHORIZED;
        }
    }

    public static final class PairResult {
        public final String token;
        public final String user;

        public PairResult(String token, String user) {
            this.token = token;
            this.user = user;
        }
    }

    private final String mBaseUrl;
    private final String mToken;

    /**
     * @param baseUrl the backend address, with or without a trailing slash
     * @param token the user token or empty
     */
    public UtubotClient(String baseUrl, @Nullable String token) {
        mBaseUrl = stripTrailingSlash(baseUrl == null ? "" : baseUrl.trim());
        mToken = token == null ? "" : token.trim();
    }

    public String getBaseUrl() {
        return mBaseUrl;
    }

    /**
     * @return true when the backend is up (no token needed)
     */
    public boolean health() throws IOException {
        return parse(() -> new JSONObject(send(builder("/health", false), 0)).optBoolean("ok"));
    }

    /**
     * Exchanges a pairing code for a user token. No token needed.
     */
    public PairResult pair(String code, String device) throws IOException {
        return parse(() -> {
            JSONObject body = new JSONObject().put("code", code).put("device", device);
            JSONObject answer = new JSONObject(send(builder("/pair", false).post(json(body)), 0));
            return new PairResult(answer.getString("token"), answer.optString("user", ""));
        });
    }

    /**
     * The setup file at an address resolved by {@link UtubotSetup#resolveUrl}. No backend or token needed.
     */
    public static UtubotSetup fetchSetup(String url) throws IOException, UtubotSetup.SetupException {
        Request request = new Request.Builder().url(url).build();

        try (Response response = sBase.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new HttpException(response.code(), "HTTP " + response.code());
            }

            String body = response.body() != null ? readBounded(response.body().byteStream(), MAX_SETUP_BYTES) : "";

            return UtubotSetup.parse(body);
        } catch (IllegalArgumentException e) {
            throw new UtubotSetup.SetupException("Not a valid address: " + url);
        }
    }

    /**
     * The whole stream as text, which may be shorter than the limit (BufferedSource.readUtf8(n) needs exactly n bytes)
     */
    static String readBounded(InputStream stream, long maxBytes) throws IOException, UtubotSetup.SetupException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] chunk = new byte[CHUNK_BYTES];
        int read;

        while ((read = stream.read(chunk)) != -1) {
            out.write(chunk, 0, read);

            if (out.size() > maxBytes) {
                throw new UtubotSetup.SetupException("The setup file is too large");
            }
        }

        return out.toString(StandardCharsets.UTF_8.name());
    }

    public Me me() throws IOException {
        return parse(() -> UtubotParser.parseMe(send(builder("/me", true), 0)));
    }

    /**
     * @param hardTimeoutMs the whole call is cancelled after it
     */
    public List<Verdict> assess(List<VideoMeta> videos, String section, int waitMs, int hardTimeoutMs) throws IOException {
        if (videos.size() > MAX_ASSESS_VIDEOS) {
            throw new IOException("Too many videos in one assess call: " + videos.size());
        }

        return parse(() -> {
            JSONArray array = new JSONArray();

            for (VideoMeta video : videos) {
                array.put(video.toJson());
            }

            JSONObject body = new JSONObject().put("videos", array).put("section", section).put("wait_ms", waitMs);
            return UtubotParser.parseAssess(send(builder("/assess", true).post(json(body)), hardTimeoutMs));
        });
    }

    public Insight insight(String videoId, @Nullable VideoMeta meta, int waitMs) throws IOException {
        HttpUrl.Builder url = urlBuilder("/videos/" + videoId + "/insight");
        url.addQueryParameter("wait_ms", String.valueOf(waitMs));
        addMeta(url, meta);
        return parse(() -> UtubotParser.parseInsight(send(authorized(url), waitMs + LONG_POLL_SLACK_MS)));
    }

    public Summary summary(String videoId, @Nullable String promptKey, @Nullable VideoMeta meta, int waitMs) throws IOException {
        HttpUrl.Builder url = urlBuilder("/videos/" + videoId + "/summary");
        url.addQueryParameter("wait_ms", String.valueOf(waitMs));

        if (promptKey != null && !promptKey.isEmpty()) {
            url.addQueryParameter("prompt", promptKey);
        }

        addMeta(url, meta);
        return parse(() -> UtubotParser.parseSummary(send(authorized(url), waitMs + LONG_POLL_SLACK_MS)));
    }

    public PromptList prompts() throws IOException {
        return parse(() -> UtubotParser.parsePrompts(send(builder("/prompts", true), 0)));
    }

    public PromptSet importPrompts(String url) throws IOException {
        return parse(() -> UtubotParser.parseImportedSet(
                send(builder("/prompts/import", true).post(json(new JSONObject().put("url", url))), IMPORT_TIMEOUT_MS)));
    }

    public void refreshPrompts() throws IOException {
        send(builder("/prompts/refresh", true).post(json(new JSONObject())), IMPORT_TIMEOUT_MS);
    }

    public void setDefaultPrompt(String key) throws IOException {
        parse(() -> send(builder("/prompts/default", true).put(json(new JSONObject().put("key", key))), 0));
    }

    public Captions captions(String videoId) throws IOException {
        return parse(() -> UtubotParser.parseCaptions(send(builder("/videos/" + videoId + "/captions", true), 0)));
    }

    /**
     * @return the status of the queued job: queued, running, ready or failed
     */
    public String prepareCaptions(String videoId) throws IOException {
        return parse(() -> {
            JSONObject body = new JSONObject().put("lang", "auto").put("translate_to", JSONObject.NULL);
            return new JSONObject(send(builder("/videos/" + videoId + "/captions", true).post(json(body)), 0)).optString("status", "queued");
        });
    }

    /**
     * The absolute address of a caption file
     */
    public String captionUrl(String trackUrl) {
        return trackUrl.startsWith("http") ? trackUrl : mBaseUrl + trackUrl;
    }

    /**
     * The Authorization header value for a backend address, null for the other hosts or without a token (the token never leaves for
     * a foreign host)
     */
    @Nullable
    public String authorizationFor(String absoluteUrl) {
        return mToken.isEmpty() || !absoluteUrl.startsWith(mBaseUrl) ? null : "Bearer " + mToken;
    }

    private interface Parser<T> {
        T parse() throws JSONException, IOException;
    }

    private static <T> T parse(Parser<T> parser) throws IOException {
        try {
            return parser.parse();
        } catch (JSONException e) {
            throw new IOException("Bad answer: " + e.getMessage(), e);
        }
    }

    private static RequestBody json(JSONObject body) {
        return RequestBody.create(body.toString(), JSON);
    }

    private static void addMeta(HttpUrl.Builder url, @Nullable VideoMeta meta) {
        if (meta == null) {
            return;
        }

        if (meta.title != null) {
            url.addQueryParameter("title", meta.title);
        }

        if (meta.channel != null) {
            url.addQueryParameter("channel", meta.channel);
        }

        if (meta.durationSec > 0) {
            url.addQueryParameter("duration_s", String.valueOf(meta.durationSec));
        }
    }

    private Request.Builder builder(String path, boolean auth) throws IOException {
        Request.Builder builder = new Request.Builder().url(urlBuilder(path).build());
        return auth ? withToken(builder) : builder;
    }

    private Request.Builder authorized(HttpUrl.Builder url) {
        return withToken(new Request.Builder().url(url.build()));
    }

    private Request.Builder withToken(Request.Builder builder) {
        return mToken.isEmpty() ? builder : builder.header("Authorization", "Bearer " + mToken);
    }

    /**
     * @param timeoutMs the whole call is cancelled after it, 0 for the client's defaults
     */
    private String send(Request.Builder builder, int timeoutMs) throws IOException {
        OkHttpClient client = timeoutMs > 0 ? sBase.newBuilder()
                .callTimeout(timeoutMs, TimeUnit.MILLISECONDS)
                .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
                .build() : sBase;

        try (Response response = client.newCall(builder.build()).execute()) {
            String body = response.body() != null ? response.body().string() : "";

            if (!response.isSuccessful()) {
                throw new HttpException(response.code(), "HTTP " + response.code() + ": " + abbreviate(body));
            }

            return body;
        }
    }

    private HttpUrl.Builder urlBuilder(String path) throws IOException {
        HttpUrl base = HttpUrl.parse(mBaseUrl + API_PREFIX + path);

        if (base == null) {
            throw new IOException("Bad backend address: " + mBaseUrl);
        }

        return base.newBuilder();
    }

    private static String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    private static String abbreviate(String text) {
        return text.length() > MAX_ERROR_CHARS ? text.substring(0, MAX_ERROR_CHARS) : text;
    }
}
