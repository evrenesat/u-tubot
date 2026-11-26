package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.nio.charset.StandardCharsets;
import java.net.ConnectException;
import java.net.Proxy;
import java.net.UnknownHostException;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

import javax.net.ssl.SSLException;

import okhttp3.Call;
import okhttp3.ConnectionPool;
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
    // Idle connections are dropped before the server's keep-alive (75 s) closes them, so a
    // request never lands on a dead connection ("unexpected end of stream").
    private static final int POOL_MAX_IDLE = 5;
    private static final int POOL_KEEP_ALIVE_SEC = 30;
    private static final int WRITE_TIMEOUT_SEC = 10;
    private static final int LONG_POLL_SLACK_MS = 10_000;
    private static final int IMPORT_TIMEOUT_MS = 30_000;
    private static final int CLIENT_CAPTIONS_TIMEOUT_MS = 30_000;
    private static final int MAX_ERROR_CHARS = 120;
    private static final int CHUNK_BYTES = 4096;
    private static final long MAX_SETUP_BYTES = 64 * 1024;
    private static final int DEFAULT_READ_TIMEOUT_SEC = 15;
    private static final int HTTP_UNAUTHORIZED = 401;
    private static final int HTTP_BAD_REQUEST = 400;
    private static final int HTTP_NOT_FOUND = 404;
    private static final int MAX_ASSESS_VIDEOS = 50;
    private static final OkHttpClient sBase = new OkHttpClient.Builder()
            .proxy(Proxy.NO_PROXY)
            .dns(Dns.SYSTEM)
            .connectTimeout(CONNECT_TIMEOUT_SEC, TimeUnit.SECONDS)
            .writeTimeout(WRITE_TIMEOUT_SEC, TimeUnit.SECONDS)
            .readTimeout(DEFAULT_READ_TIMEOUT_SEC, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .connectionPool(new ConnectionPool(POOL_MAX_IDLE, POOL_KEEP_ALIVE_SEC, TimeUnit.SECONDS))
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

        /**
         * The backend doesn't know the prompt asked for (e.g. prompt=panel on a backend without the panel prompt)
         */
        public boolean isPromptRejected() {
            return code == HTTP_BAD_REQUEST || code == HTTP_NOT_FOUND;
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
    private final Set<Call> mCalls = ConcurrentHashMap.newKeySet();
    private volatile boolean mIsCancelled;

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
     * Both clients talk to the same backend with the same token
     */
    boolean isSameConnectionAs(UtubotClient other) {
        return mBaseUrl.equals(other.mBaseUrl) && mToken.equals(other.mToken);
    }

    /**
     * Cancels the calls of this client in flight, and refuses new ones. Safe from any thread.
     */
    public void cancel() {
        mIsCancelled = true;

        for (Call call : mCalls) {
            call.cancel();
        }
    }

    public boolean isCancelled() {
        return mIsCancelled;
    }

    /**
     * @return true when the backend is up (no token needed)
     */
    public boolean health() throws IOException {
        return parse(() -> new JSONObject(send(builder("/health", false), 0)).optBoolean("ok"));
    }

    /**
     * The schema of the cacheable data the backend reports (`GET /v1/health`, no token needed): it changes only when the shape of
     * the answers changes, never with a deploy. A backend that reports none has the first schema.
     */
    public String cacheSchema() throws IOException {
        return parse(() -> new JSONObject(send(builder("/health", false), 0)).optString("cache_schema", "1"));
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
        UtubotBusyTracker.instance().begin();

        try (Response response = sBase.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new HttpException(response.code(), "HTTP " + response.code());
            }

            String body = response.body() != null ? readBounded(response.body().byteStream(), MAX_SETUP_BYTES) : "";

            return UtubotSetup.parse(body);
        } catch (IllegalArgumentException e) {
            throw new UtubotSetup.SetupException("Not a valid address: " + url);
        } finally {
            UtubotBusyTracker.instance().end();
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

    /**
     * Asks the backend to make the transcript of a video without captions in the background
     * (`POST /v1/videos/{id}/transcribe`). The answer says where it stands, like {@link #transcript}.
     */
    public Transcript transcribe(String videoId, @Nullable VideoMeta meta) throws IOException {
        HttpUrl.Builder url = urlBuilder("/videos/" + videoId + "/transcribe");
        addMeta(url, meta);
        return parse(() -> UtubotParser.parseTranscript(send(authorized(url).post(json(new JSONObject())), 0)));
    }

    /**
     * The Retry action (`POST /v1/videos/{id}/retry`): the backend forgets what it remembers about a failure of the video, so the next
     * request really tries again. Stored successes stay.
     */
    public void forgetFailures(String videoId) throws IOException {
        parse(() -> new JSONObject(send(builder("/videos/" + videoId + "/retry", true).post(json(new JSONObject())), 0)).optBoolean("ok"));
    }

    /**
     * Where the transcript of a video stands (`GET /v1/videos/{id}/transcript`): cheap, it never starts any work
     */
    public Transcript transcript(String videoId) throws IOException {
        return parse(() -> UtubotParser.parseTranscript(send(builder("/videos/" + videoId + "/transcript", true), 0)));
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
     * Gives the backend the caption tracks the player already holds (`POST /v1/videos/{id}/captions/client`), so it need not fetch them
     * from YouTube itself. Answers whether the backend kept them.
     */
    public boolean uploadCaptions(String videoId, List<UtubotModels.ClientCaptionTrack> tracks) throws IOException {
        JSONArray array = new JSONArray();

        try {
            for (UtubotModels.ClientCaptionTrack track : tracks) {
                array.put(new JSONObject()
                        .put("lang", track.lang)
                        .put("kind", track.kind)
                        .put("name", track.name)
                        .put("format", track.format)
                        .put("body", track.body)
                        .put("original", track.original));
            }
        } catch (JSONException e) {
            throw new IOException(e);
        }

        return parse(() -> new JSONObject(send(builder("/videos/" + videoId + "/captions/client", true)
                .post(json(new JSONObject().put("tracks", array))), CLIENT_CAPTIONS_TIMEOUT_MS)).optBoolean("stored"));
    }

    //region Director's cuts

    /**
     * The presets of a video and where their cuts stand (`GET /v1/videos/{id}/cuts`): cheap, it starts nothing
     */
    public CutList cuts(String videoId) throws IOException {
        return cuts(videoId, null);
    }

    /**
     * The presets of a video, with the mode its channel resolves to (`GET /v1/videos/{id}/cuts?channel_id=...`)
     */
    public CutList cuts(String videoId, @Nullable VideoMeta meta) throws IOException {
        return parse(() -> UtubotParser.parseCuts(send(authorized(cutUrl(videoId, meta)), 0)));
    }

    /**
     * Stores a mode for one channel (`PUT /v1/cut-channels/{channel_id}`); null clears it and follows the user default
     */
    public void setChannelMode(String channelId, @Nullable String mode, @Nullable String channelName) throws IOException {
        parse(() -> {
            JSONObject body = new JSONObject();
            body.put("mode", mode == null ? JSONObject.NULL : mode);

            if (channelName != null) {
                body.put("channel_name", channelName);
            }

            return send(authorized(urlBuilder("/cut-channels/" + channelId)).put(json(body)), 0);
        });
    }

    /**
     * Clears a channel's own mode (`DELETE /v1/cut-channels/{channel_id}`), so it follows the user default again
     */
    public void clearChannelMode(String channelId) throws IOException {
        send(authorized(urlBuilder("/cut-channels/" + channelId)).delete(), 0);
    }

    /**
     * Asks for a cut (`POST /v1/videos/{id}/cuts`): a preset, a typed prompt, or a waiting request the phone fills. The video facts
     * the caller knows ride along, so the phone queue can show them at once.
     *
     * @param presetId the preset to build, or null
     * @param prompt what to keep, or null (a preset and a prompt are mutually exclusive)
     * @param awaitPrompt true creates a waiting request for the phone instead of building now
     */
    public CutRequest requestCut(String videoId, @Nullable String presetId, @Nullable String prompt, boolean awaitPrompt,
                                 @Nullable VideoMeta meta) throws IOException {
        return requestCut(videoId, presetId, prompt, awaitPrompt, meta, null, false);
    }

    /**
     * The same request with an explicit cut mode (`quick` or `watched`); null follows the caller's default.
     */
    public CutRequest requestCut(String videoId, @Nullable String presetId, @Nullable String prompt, boolean awaitPrompt,
                                 @Nullable VideoMeta meta, @Nullable String mode) throws IOException {
        return requestCut(videoId, presetId, prompt, awaitPrompt, meta, mode, false);
    }

    /**
     * As above; `force` builds from u·tubot's own audio transcript even when the video has captions.
     */
    public CutRequest requestCut(String videoId, @Nullable String presetId, @Nullable String prompt, boolean awaitPrompt,
                                 @Nullable VideoMeta meta, boolean force) throws IOException {
        return requestCut(videoId, presetId, prompt, awaitPrompt, meta, null, force);
    }

    /**
     * The full request: an explicit cut mode and `force`.
     */
    public CutRequest requestCut(String videoId, @Nullable String presetId, @Nullable String prompt, boolean awaitPrompt,
                                 @Nullable VideoMeta meta, @Nullable String mode, boolean force) throws IOException {
        return parse(() -> {
            JSONObject body = new JSONObject();

            if (force) {
                body.put("force", true);
            }

            if (awaitPrompt) {
                body.put("await_prompt", true);
            } else if (presetId != null) {
                body.put("preset", presetId);
            } else if (prompt != null) {
                body.put("prompt", prompt);
            } else {
                throw new IOException("A cut needs a preset, a prompt or a waiting request");
            }

            if (mode != null) {
                body.put("mode", mode);
            }

            return UtubotParser.parseCutRequest(send(authorized(cutUrl(videoId, meta)).post(json(body)), 0));
        });
    }

    /**
     * Remembers what the viewer chose for a video (`PUT /v1/videos/{id}/cut-choice`): a preset, one of their requests, or off.
     */
    public void chooseCut(String videoId, @Nullable String presetId, @Nullable String requestId, boolean off) throws IOException {
        JSONObject body = new JSONObject();

        try {
            if (off) {
                body.put("off", true);
            } else if (presetId != null) {
                body.put("preset", presetId);
            } else if (requestId != null) {
                body.put("request", requestId);
            } else {
                throw new IOException("A cut choice needs a preset, a request or off");
            }
        } catch (JSONException e) {
            throw new IOException(e.getMessage());
        }

        send(builder("/videos/" + videoId + "/cut-choice", true).put(json(body)), 0);
    }

    /**
     * One cut request, long-polling while it waits or builds (`GET /v1/cuts/{id}`)
     *
     * @param waitMs how long the backend may hold the answer, 0 for its default
     */
    public CutRequest cut(String requestId, int waitMs) throws IOException {
        HttpUrl.Builder url = urlBuilder("/cuts/" + requestId);

        if (waitMs > 0) {
            url.addQueryParameter("wait_ms", String.valueOf(waitMs));
        }

        return parse(() -> UtubotParser.parseCutRequest(send(authorized(url), waitMs + LONG_POLL_SLACK_MS)));
    }

    /**
     * The short address a phone opens straight to a request's cut sheet (`GET /cuts/{id}`, no auth, the backend redirects)
     */
    public String cutRequestUrl(String requestId) {
        return mBaseUrl + "/cuts/" + requestId;
    }

    private HttpUrl.Builder cutUrl(String videoId, @Nullable VideoMeta meta) throws IOException {
        HttpUrl.Builder url = urlBuilder("/videos/" + videoId + "/cuts");

        if (meta != null) {
            if (meta.title != null) {
                url.addQueryParameter("title", meta.title);
            }

            if (meta.channel != null) {
                url.addQueryParameter("channel", meta.channel);
            }

            if (meta.channelId != null) {
                url.addQueryParameter("channel_id", meta.channelId);
            }

            if (meta.durationSec > 0) {
                url.addQueryParameter("duration_s", String.valueOf(meta.durationSec));
            }

            if (meta.isLive) {
                url.addQueryParameter("is_live", "true");
            }
        }

        return url;
    }

    //endregion

    //region Processed videos

    /**
     * The caller's recently processed videos (`GET /v1/processed`): cheap, it starts nothing
     *
     * @param limit how many videos, 1 to 200; 0 for the backend's default
     */
    public ProcessedList processed(int limit) throws IOException {
        HttpUrl.Builder url = urlBuilder("/processed");

        if (limit > 0) {
            url.addQueryParameter("limit", String.valueOf(limit));
        }

        return parse(() -> UtubotParser.parseProcessed(send(authorized(url), 0)));
    }

    /**
     * The version history (`GET /v1/changelog`), as the backend sends it: see {@link UtubotChangelog#parse}
     *
     * @param kind {@link UtubotChangelog#KIND_APP} or {@link UtubotChangelog#KIND_BACKEND}
     */
    public String changelogJson(String kind) throws IOException {
        HttpUrl.Builder url = urlBuilder("/changelog");
        url.addQueryParameter("kind", kind);

        return send(authorized(url), 0);
    }

    //endregion

    /**
     * @return the status of the queued job: queued, running, ready or failed
     */
    public String prepareCaptions(String videoId) throws IOException {
        return prepareCaptions(videoId, false);
    }

    public String prepareCaptions(String videoId, boolean force) throws IOException {
        return parse(() -> {
            JSONObject body = new JSONObject().put("lang", "auto").put("translate_to", JSONObject.NULL)
                    .put("force", force);
            return new JSONObject(send(builder("/videos/" + videoId + "/captions", true).post(json(body)), 0)).optString("status", "queued");
        });
    }

    /**
     * The file of a caption track, at most {@link UtubotCaptionStore#MAX_FILE_BYTES} long
     */
    public byte[] captionFile(String trackUrl) throws IOException {
        String url = captionUrl(trackUrl);
        Request.Builder builder;

        try {
            builder = new Request.Builder().url(url);
        } catch (IllegalArgumentException e) {
            throw new IOException("Bad caption address: " + url);
        }

        String authorization = authorizationFor(url);

        if (authorization != null) {
            builder.header("Authorization", authorization);
        }

        if (mIsCancelled) {
            throw new IOException("Cancelled");
        }

        Call call = sBase.newCall(builder.build());
        mCalls.add(call);
        UtubotBusyTracker.instance().begin();

        try (Response response = call.execute()) {
            if (!response.isSuccessful()) {
                throw new HttpException(response.code(), "HTTP " + response.code());
            }

            return response.body() != null ? readBoundedBytes(response.body().byteStream(), UtubotCaptionStore.MAX_FILE_BYTES) : new byte[0];
        } finally {
            mCalls.remove(call);
            UtubotBusyTracker.instance().end();
        }
    }

    private static byte[] readBoundedBytes(InputStream stream, int maxBytes) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] chunk = new byte[CHUNK_BYTES];
        int read;

        while ((read = stream.read(chunk)) != -1) {
            out.write(chunk, 0, read);

            if (out.size() > maxBytes) {
                throw new IOException("The file is too large");
            }
        }

        return out.toByteArray();
    }

    /**
     * The absolute address of a caption file
     */
    public String captionUrl(String trackUrl) {
        return trackUrl.startsWith("http") ? trackUrl : mBaseUrl + trackUrl;
    }

    /**
     * The Authorization header value for an address of the backend, null for anything else or without a token. The token never
     * leaves for a foreign address: scheme, host and port must be the backend's exactly (a prefix of the text is not enough:
     * https://backend.example.com.evil.net/ starts with https://backend.example.com) and the path must lie under the backend's.
     */
    @Nullable
    public String authorizationFor(@Nullable String absoluteUrl) {
        if (mToken.isEmpty() || absoluteUrl == null) {
            return null;
        }

        HttpUrl base = HttpUrl.parse(mBaseUrl);
        HttpUrl target = HttpUrl.parse(absoluteUrl.trim());

        return base != null && target != null && isUnder(base, target) ? "Bearer " + mToken : null;
    }

    private static boolean isUnder(HttpUrl base, HttpUrl target) {
        if (!base.scheme().equals(target.scheme()) || !base.host().equals(target.host()) || base.port() != target.port()) {
            return false;
        }

        List<String> basePath = withoutTrailingEmpty(base.encodedPathSegments());
        List<String> targetPath = target.encodedPathSegments();

        return targetPath.size() >= basePath.size() && targetPath.subList(0, basePath.size()).equals(basePath);
    }

    private static List<String> withoutTrailingEmpty(List<String> segments) {
        int size = segments.size();

        while (size > 0 && segments.get(size - 1).isEmpty()) {
            size--;
        }

        return segments.subList(0, size);
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
        Request request = builder.build();

        if (mIsCancelled) {
            throw new IOException("Cancelled");
        }

        try {
            return execute(client, request);
        } catch (IOException e) {
            if (!isDroppedConnection(request, e)) {
                throw e;
            }

            // The pool handed out an idle connection that the server had closed: the second try opens a fresh one
            return execute(client, request);
        }
    }

    /**
     * A GET that failed for a reason a second try can cure: the server closed a kept-alive connection (the client doesn't retry
     * by itself, so no request is sent twice by accident). Timeouts, refused or unresolvable hosts, TLS and error statuses are not.
     */
    private boolean isDroppedConnection(Request request, IOException error) {
        return "GET".equals(request.method()) && !mIsCancelled && !(error instanceof HttpException) && !(error instanceof InterruptedIOException) &&
                !(error instanceof UnknownHostException) && !(error instanceof ConnectException) && !(error instanceof SSLException);
    }

    private String execute(OkHttpClient client, Request request) throws IOException {
        Call call = client.newCall(request);
        mCalls.add(call);
        UtubotBusyTracker.instance().begin();

        try {
            if (mIsCancelled) {
                call.cancel();
            }

            try (Response response = call.execute()) {
                String body = response.body() != null ? response.body().string() : "";

                if (!response.isSuccessful()) {
                    throw new HttpException(response.code(), "HTTP " + response.code() + ": " + abbreviate(body));
                }

                return body;
            }
        } finally {
            mCalls.remove(call);
            UtubotBusyTracker.instance().end();
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
