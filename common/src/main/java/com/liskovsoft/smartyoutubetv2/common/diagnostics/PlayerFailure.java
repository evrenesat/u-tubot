package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import android.content.Context;

import androidx.annotation.Nullable;

import com.google.android.exoplayer2.Format;
import com.liskovsoft.smartyoutubetv2.common.BuildConfig;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.youtubeapi.videoinfo.V2.ClientAttempts.Attempt;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

/**
 * A player failure and what the app did about it, recorded to {@link PlayerFailureLog}. Built where the failure is handled and
 * recorded once that's done.
 */
public final class PlayerFailure {
    public static final String KIND_ENGINE_ERROR = "engine_error";
    public static final String KIND_FORMAT_ERROR = "format_error";
    public static final String KIND_UNPLAYABLE = "unplayable";
    public static final String KIND_EMPTY_FORMATS = "empty_formats";
    public static final String KIND_STALL = "stall";
    public static final String KIND_TRACK_LOAD_ERROR = "track_load_error";
    public static final String PROTOCOL_DASH = "dash";
    public static final String PROTOCOL_SABR = "sabr";
    public static final String PROTOCOL_DASH_LIVE = "dash_live";
    public static final String PROTOCOL_HLS = "hls";
    public static final String PROTOCOL_URL_LIST = "url_list";
    public static final String PROTOCOL_PROGRESSIVE = "progressive";
    private static final int MAX_STACK_FRAMES = 20;
    private static final int MAX_CAUSES = 8;
    private final Context mContext;
    private final String mKind;
    private final List<String> mActions = new ArrayList<>();
    private String mVideoId;
    private Boolean mIsLive;
    private Long mPositionMs;
    private Long mDurationMs;
    private Boolean mStartedPlaying;
    private JSONObject mError;
    private String mErrorClass;
    private String mErrorMessage;
    private JSONObject mPlayability;
    private JSONObject mHttp;
    private Integer mHttpCode;
    private String mEngineSelected;
    private String mEngineEffective;
    private String mClient;
    private String mProtocol;
    private String mVideoFormat;
    private String mAudioFormat;
    private List<Attempt> mClientAttempts;
    /**
     * What SABR's server made of the video's poToken (see ProtectionStatuses), when it's recorded
     */
    private JSONArray mProtection;
    private JSONObject mFormats;
    /**
     * How it played up to the failure (see FormatAttempts#getPlaying)
     */
    private JSONObject mPlaying;
    private JSONObject mSettings;
    private JSONObject mDetails;
    /**
     * What the player was told and did before it (see PlayerCommands)
     */
    private JSONArray mCommands;
    private long mTs;
    /**
     * Of the process it happened in, -1 when not known (see #withoutState)
     */
    private long mSinceProcessStartMs = -1;
    private boolean mIsStateIncluded = true;
    /**
     * Once: a handler may record it early (e.g. before the app restarts), then in its finally
     */
    private boolean mIsRecorded;

    private PlayerFailure(Context context, String kind) {
        mContext = context.getApplicationContext();
        mKind = kind;
    }

    /**
     * With the network engine chosen and the one in use
     */
    public static PlayerFailure create(Context context, String kind) {
        PlayerFailure failure = new PlayerFailure(context, kind);
        failure.mSinceProcessStartMs = VideoStarts.getSinceProcessStartMs();
        failure.mEngineSelected = Utils.getNetworkEngineId(PlayerTweaksData.instance(context).getPlayerDataSource());
        failure.mCommands = PlayerCommands.snapshot();
        Scrubber.update(context);

        try {
            // Before the fix: it may change them (switch the engine, turn the subtitles off…)
            failure.mSettings = DiagnosticsReport.buildPlaybackSettings(context);
        } catch (JSONException | RuntimeException e) {
            // Recorded without them
        }

        try {
            failure.mEngineEffective = Utils.getEffectiveNetworkEngine(context);
        } catch (RuntimeException e) {
            // Cronet couldn't be checked: the failure is recorded without it
        }

        return failure;
    }

    public String getKind() {
        return mKind;
    }

    /**
     * Of the video playing, when there's no Video at hand (e.g. a crash)
     */
    public PlayerFailure videoId(@Nullable String videoId) {
        mVideoId = videoId;

        return this;
    }

    /**
     * It happened before it's recorded (e.g. an app exit found on the next start)
     */
    public PlayerFailure at(long ts) {
        mTs = ts;

        return this;
    }

    long getTs() {
        return mTs;
    }

    public PlayerFailure video(@Nullable Video video) {
        if (video != null) {
            mVideoId = video.videoId;
            mIsLive = video.isLive;
        }

        return this;
    }

    public PlayerFailure playback(long positionMs, long durationMs, boolean startedPlaying) {
        mStartedPlaying = startedPlaying;

        return position(positionMs, durationMs);
    }

    public PlayerFailure position(long positionMs, long durationMs) {
        mPositionMs = positionMs;
        mDurationMs = durationMs;

        return this;
    }

    public PlayerFailure formats(@Nullable FormatItem video, @Nullable FormatItem audio) {
        mVideoFormat = describeVideo(video);
        mAudioFormat = describeAudio(audio);

        return this;
    }

    /**
     * The YouTube client the formats are from and the way they're played (see the PROTOCOL_ constants)
     */
    public PlayerFailure source(@Nullable String client, @Nullable String protocol) {
        mClient = client;
        mProtocol = protocol;

        return this;
    }

    /**
     * @param type see PlayerEventListener.ERROR_TYPE_
     */
    public PlayerFailure engineError(int type, int rendererIndex, @Nullable Throwable error) {
        error(error);

        try {
            mError.put("type", getTypeName(type));
            mError.put("rendererIndex", rendererIndex);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return this;
    }

    public PlayerFailure error(@Nullable Throwable error) {
        mError = new JSONObject();

        if (error == null) {
            return this;
        }

        mErrorClass = error.getClass().getSimpleName();
        mErrorMessage = scrub(error.getMessage());
        JSONArray causes = new JSONArray();
        Throwable root = error;

        for (Throwable cause = error.getCause(); cause != null && cause != root && causes.length() < MAX_CAUSES; cause = cause.getCause()) {
            causes.put(cause.getClass().getSimpleName() + ": " + scrub(cause.getMessage()));
            root = cause;
        }

        JSONArray stack = new JSONArray();
        StackTraceElement[] frames = root.getStackTrace();

        for (int i = 0; i < frames.length && i < MAX_STACK_FRAMES; i++) {
            stack.put(frames[i].toString());
        }

        try {
            mError.put("class", mErrorClass);
            mError.put("message", mErrorMessage != null ? mErrorMessage : JSONObject.NULL);
            mError.put("causes", causes);
            mError.put("stack", stack);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return this;
    }

    public PlayerFailure playability(@Nullable String status, @Nullable String reason) {
        mPlayability = new JSONObject();

        try {
            mPlayability.put("status", status != null ? status : JSONObject.NULL);
            mPlayability.put("reason", reason != null ? reason : JSONObject.NULL);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return this;
    }

    /**
     * A segment of the track failed with the HTTP code
     *
     * @param track audio, video or other
     */
    public PlayerFailure http(int code, String track, @Nullable Format failed) {
        mHttp = new JSONObject();
        mHttpCode = code;

        try {
            mHttp.put("code", code);
            mHttp.put("track", track);
            putOpt(mHttp, "format", "audio".equals(track) ? describeAudio(failed) : describeVideo(failed));
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return this;
    }

    /**
     * Why each YouTube client failed to give the formats (see ClientAttempts)
     */
    public PlayerFailure clientAttempts(@Nullable List<Attempt> attempts) {
        mClientAttempts = attempts;

        return this;
    }

    /**
     * What else tells about it, e.g. the frames dropped
     */
    public PlayerFailure detail(String name, @Nullable Object value) {
        if (mDetails == null) {
            mDetails = new JSONObject();
        }

        try {
            mDetails.put(name, value != null ? value : JSONObject.NULL);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return this;
    }

    /**
     * Something done about it, e.g. "reload_video", in the order done
     */
    public PlayerFailure action(String action) {
        mActions.add(action);

        return this;
    }

    public List<String> getActions() {
        return mActions;
    }

    /**
     * To the log. Never throws: it's recorded while the failure is being fixed.
     */
    public void record() {
        if (mIsRecorded) {
            return;
        }

        mIsRecorded = true;

        try {
            mFormats = FormatAttempts.snapshot(mContext, mVideoId);
            mPlaying = mIsStateIncluded ? FormatAttempts.getPlaying(mVideoId) : null;
            // Of this process: not of a failure from one before (e.g. an app exit), whose video may be playing again
            mProtection = mIsStateIncluded ? ProtectionStatuses.snapshot(mVideoId) : null;
            PlayerFailureLog.instance(mContext).record(this);
        } catch (RuntimeException e) {
            android.util.Log.e("PlayerFailure", "Can't record: " + e);
        }
    }

    /**
     * Written before it returns (see PlayerFailureLog#recordNow): the app is about to die. Never throws.
     */
    public void recordNow() {
        if (mIsRecorded) {
            return;
        }

        mIsRecorded = true;

        try {
            mFormats = FormatAttempts.snapshot(mContext, mVideoId);
            mPlaying = mIsStateIncluded ? FormatAttempts.getPlaying(mVideoId) : null;
            // Of this process: not of a failure from one before (e.g. an app exit), whose video may be playing again
            mProtection = mIsStateIncluded ? ProtectionStatuses.snapshot(mVideoId) : null;
            PlayerFailureLog.instance(mContext).recordNow(this);
        } catch (RuntimeException e) {
            android.util.Log.e("PlayerFailure", "Can't record: " + e);
        }
    }

    /**
     * Not where the device is at now: e.g. an app exit found on the next start
     */
    public PlayerFailure withoutState() {
        mIsStateIncluded = false;
        // It happened in a process before this one
        mSinceProcessStartMs = -1;

        return this;
    }

    /**
     * Built in the background, for the lines written only (see PlayerFailureLog)
     */
    @Nullable
    PlayerFailureLog.StateSource getStateSource() {
        if (!mIsStateIncluded) {
            return null;
        }

        Context context = mContext;
        long afrSwitchTimeMs = PlayerData.instance(context).getAfrSwitchTimeMs();

        return () -> DeviceCapabilities.buildState(context, afrSwitchTimeMs);
    }

    /**
     * The same failure again: its repeats within a minute are counted, not written (see PlayerFailureLog)
     */
    String getSignature() {
        return mKind + "|" + mVideoId + "|" + mErrorClass + "|" + mErrorMessage + "|" + mHttpCode;
    }

    JSONObject toJson(long ts, String appVersion, int appVersionCode, int account) {
        JSONObject result = new JSONObject();

        try {
            result.put("ts", ts);
            result.put("time", formatUtc(ts));
            result.put("appVersion", appVersion);
            result.put("appVersionCode", appVersionCode);
            result.put("account", account);
            putOpt(result, "build", BuildConfig.BUILD_ID);

            if (mSinceProcessStartMs >= 0) {
                result.put("sinceProcessStartMs", mSinceProcessStartMs);
            }

            result.put("kind", mKind);
            putOpt(result, "videoId", mVideoId);
            putOpt(result, "live", mIsLive);
            putOpt(result, "positionMs", mPositionMs);
            putOpt(result, "durationMs", mDurationMs);
            putOpt(result, "startedPlaying", mStartedPlaying);
            putOpt(result, "playing", mPlaying);
            putOpt(result, "error", mError);
            putOpt(result, "playability", mPlayability);
            putOpt(result, "http", mHttp);
            putOpt(result, "details", mDetails);

            JSONObject player = new JSONObject();
            putOpt(player, "engineSelected", mEngineSelected);
            putOpt(player, "engineEffective", mEngineEffective);
            putOpt(player, "client", mClient);
            putOpt(player, "protocol", mProtocol);
            putOpt(player, "video", mVideoFormat);
            putOpt(player, "audio", mAudioFormat);
            result.put("player", player);
            putOpt(result, "formats", mFormats);
            putOpt(result, "settings", mSettings);

            if (mClientAttempts != null && !mClientAttempts.isEmpty()) {
                JSONArray attempts = new JSONArray();

                for (Attempt attempt : mClientAttempts) {
                    JSONObject item = new JSONObject();
                    item.put("client", attempt.client);
                    item.put("result", attempt.result);
                    putOpt(item, "status", attempt.status);
                    putOpt(item, "reason", attempt.reason);
                    putOpt(item, "error", scrub(attempt.error));
                    attempts.put(item);
                }

                result.put("clientAttempts", attempts);
            }

            putOpt(result, "protection", mProtection);
            putOpt(result, "commands", mCommands);

            result.put("actions", new JSONArray(mActions));
            result.put("repeats", 0);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return result;
    }

    /**
     * E.g. 2026-10-23T07:31:53.013Z
     */
    private static String formatUtc(long ms) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));

        return format.format(new Date(ms));
    }

    private static void putOpt(JSONObject json, String name, @Nullable Object value) throws JSONException {
        if (value != null) {
            json.put(name, value);
        }
    }

    private static String getTypeName(int type) {
        switch (type) {
            case PlayerEventListener.ERROR_TYPE_SOURCE:
                return "SOURCE";
            case PlayerEventListener.ERROR_TYPE_RENDERER:
                return "RENDERER";
            case PlayerEventListener.ERROR_TYPE_UNEXPECTED:
                return "UNEXPECTED";
            default:
                return "TYPE_" + type;
        }
    }

    /**
     * A URL keeps its host and path, its query is left out
     */
    @Nullable
    static String scrub(@Nullable String text) {
        return Scrubber.scrub(text);
    }

    /**
     * E.g. "1920x1080 vp09 30fps"
     */
    @Nullable
    static String describeVideo(@Nullable FormatItem item) {
        if (item == null) {
            return null;
        }

        Format format = item.getTrack() != null ? item.getTrack().format : null;

        if (format != null) {
            return describeVideo(format);
        }

        return item.getWidth() > 0 && item.getHeight() > 0 ? item.getWidth() + "x" + item.getHeight() : null;
    }

    @Nullable
    static String describeVideo(@Nullable Format format) {
        // E.g. the settings' auto
        if (format == null || (format.width <= 0 && format.height <= 0 && format.codecs == null && format.sampleMimeType == null)) {
            return null;
        }

        String size = format.width > 0 && format.height > 0 ? format.width + "x" + format.height + " " : "";
        String fps = format.frameRate > 0 ? " " + Math.round(format.frameRate) + "fps" : "";

        return size + getCodec(format) + fps;
    }

    /**
     * E.g. "opus 160k"
     */
    @Nullable
    static String describeAudio(@Nullable FormatItem item) {
        return item != null && item.getTrack() != null ? describeAudio(item.getTrack().format) : null;
    }

    @Nullable
    private static String describeAudio(@Nullable Format format) {
        // E.g. the settings' auto
        if (format == null || (format.codecs == null && format.sampleMimeType == null)) {
            return null;
        }

        return format.bitrate > 0 ? getCodec(format) + " " + format.bitrate / 1000 + "k" : getCodec(format);
    }

    /**
     * E.g. vp09 of vp09.00.40.08
     */
    private static String getCodec(Format format) {
        String codecs = format.codecs != null ? format.codecs : format.sampleMimeType;

        if (codecs == null) {
            return "unknown";
        }

        int end = codecs.indexOf('.');

        return end > 0 ? codecs.substring(0, end) : codecs;
    }
}
