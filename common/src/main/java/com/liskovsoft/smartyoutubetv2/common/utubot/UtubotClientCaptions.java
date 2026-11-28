package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.googlecommon.common.helpers.DefaultHeaders;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemFormatInfo;
import com.liskovsoft.mediaserviceinterfaces.data.MediaSubtitle;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.okhttp.OkHttpManager;
import com.liskovsoft.sharedutils.querystringparser.UrlQueryString;
import com.liskovsoft.sharedutils.querystringparser.UrlQueryStringFactory;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ClientCaptionTrack;

import java.io.IOException;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import io.reactivex.Observable;
import io.reactivex.schedulers.Schedulers;
import okhttp3.Response;

/**
 * Gives the backend the caption tracks the player already got from YouTube, once per video per app session, so the server need not ask
 * YouTube for them itself (its yt-dlp requests are rate limited). Runs in the background: a failure is logged and never shown.<br/>
 * No extra YouTube request beyond the timed text of at most two tracks: the original-language one (YouTube's automatic track, else the
 * authored one in the user's language) and the user's caption language.
 */
public final class UtubotClientCaptions {
    private static final String TAG = UtubotClientCaptions.class.getSimpleName();
    private static final String TYPE_ASR = "asr";
    private static final String VSS_AUTO_PREFIX = "a.";
    private static final String PARAM_TRANSLATED = "tlang=";
    private static final String PARAM_VARIANT_DUB = "variant=timing-optimized";
    private static final String PARAM_FORMAT = "fmt";
    /** The backend refuses a track over this (its `[transcripts] client_max_track_bytes` default) */
    public static final int MAX_TRACK_BYTES = 2 * 1024 * 1024;
    /** How many videos an app session remembers it has handed over */
    static final int MAX_REMEMBERED_VIDEOS = 200;
    private static final int CHUNK_BYTES = 8192;
    private static final Set<String> sDone = Collections.synchronizedSet(new LinkedHashSet<>());

    /** A track chosen for upload, before its timed text is fetched */
    static final class Pick {
        final String url;
        final String lang;
        final String kind;
        final String name;
        final boolean original;

        Pick(String url, String lang, String kind, String name, boolean original) {
            this.url = url;
            this.lang = lang;
            this.kind = kind;
            this.name = name;
            this.original = original;
        }
    }

    interface BodySource {
        /** The track's timed text, null when it is over the size limit */
        @Nullable
        String fetch(String url) throws IOException;
    }

    interface Uploader {
        void upload(String videoId, List<ClientCaptionTrack> tracks) throws IOException;
    }

    private UtubotClientCaptions() {
    }

    /**
     * Call when the player has the video's caption tracks
     */
    public static void onFormatInfo(Context context, @Nullable String videoId, @Nullable MediaItemFormatInfo formatInfo, @Nullable String userLanguage) {
        if (context == null || videoId == null || formatInfo == null || formatInfo.isLive()) {
            return;
        }

        UtubotSettings settings = UtubotManager.instance(context).getSettings();

        if (!settings.isConfigured() || settings.getToken().isEmpty()) {
            return;
        }

        List<Pick> picks = select(formatInfo.getSubtitles(), userLanguage);

        if (picks.isEmpty() || !claim(videoId)) {
            return;
        }

        UtubotManager manager = UtubotManager.instance(context);
        Observable.fromCallable(() -> {
                    handOver(videoId, picks, UtubotClientCaptions::download, (id, tracks) -> {
                        if (!manager.newClient().background().uploadCaptions(id, tracks)) {
                            Log.d(TAG, "%s: the backend kept its own captions", id);
                        }
                    });
                    return true;
                })
                .subscribeOn(Schedulers.io())
                .subscribe(done -> { }, error -> {
                    // The server fetches them itself, and the next play tries again
                    release(videoId);
                    Log.e(TAG, "%s: can't give the captions to the backend: %s", videoId, error.getMessage());
                });
    }

    /**
     * True once per video: the caller that gets it uploads
     */
    static boolean claim(String videoId) {
        synchronized (sDone) {
            if (sDone.contains(videoId)) {
                return false;
            }

            sDone.add(videoId);

            if (sDone.size() > MAX_REMEMBERED_VIDEOS) {
                sDone.remove(sDone.iterator().next());
            }

            return true;
        }
    }

    static void release(String videoId) {
        sDone.remove(videoId);
    }

    static void forgetAll() {
        sDone.clear();
    }

    /**
     * Fetches the picked tracks and uploads what could be read. Nothing is uploaded when no track came.
     */
    static void handOver(String videoId, List<Pick> picks, BodySource source, Uploader uploader) throws IOException {
        List<ClientCaptionTrack> tracks = new ArrayList<>();

        for (Pick pick : picks) {
            String body = source.fetch(pick.url);

            if (body == null || body.trim().isEmpty()) {
                continue;
            }

            tracks.add(new ClientCaptionTrack(pick.lang, pick.kind, pick.name, ClientCaptionTrack.FORMAT_JSON3, body, pick.original));
        }

        if (!tracks.isEmpty()) {
            uploader.upload(videoId, tracks);
        }
    }

    /**
     * At most two tracks of the player's own: the original-language one and the one in the user's caption language. Translated
     * tracks and the automatic captions of a dubbed audio are never taken, they are not what the video says.
     */
    static List<Pick> select(@Nullable List<MediaSubtitle> subtitles, @Nullable String userLanguage) {
        if (subtitles == null) {
            return Collections.emptyList();
        }

        MediaSubtitle auto = null;
        MediaSubtitle userManual = null;
        MediaSubtitle userAuto = null;
        MediaSubtitle firstManual = null;
        String wanted = baseOf(userLanguage);

        for (MediaSubtitle subtitle : subtitles) {
            String url = subtitle.getBaseUrl();

            if (url == null || url.contains(PARAM_TRANSLATED) || url.contains(PARAM_VARIANT_DUB) || subtitle.getLanguageCode() == null) {
                continue;
            }

            boolean isAuto = isAuto(subtitle);
            boolean isUserLanguage = !wanted.isEmpty() && wanted.equals(baseOf(subtitle.getLanguageCode()));

            if (isAuto) {
                auto = auto == null ? subtitle : auto;
                userAuto = isUserLanguage && userAuto == null ? subtitle : userAuto;
            } else {
                firstManual = firstManual == null ? subtitle : firstManual;
                userManual = isUserLanguage && userManual == null ? subtitle : userManual;
            }
        }

        MediaSubtitle original = auto;
        MediaSubtitle user = userManual != null ? userManual : userAuto;
        List<Pick> picks = new ArrayList<>();

        if (original != null) {
            picks.add(pick(original, true));
        } else if (user == null && firstManual != null) {
            // Only authored tracks: the first is the creator's own language
            picks.add(pick(firstManual, false));
        }

        if (user != null && user != original) {
            picks.add(pick(user, false));
        }

        return picks;
    }

    private static Pick pick(MediaSubtitle subtitle, boolean original) {
        UrlQueryString query = UrlQueryStringFactory.parse(subtitle.getBaseUrl());
        query.set(PARAM_FORMAT, ClientCaptionTrack.FORMAT_JSON3);
        String name = subtitle.getName() == null ? "" : subtitle.getName();
        return new Pick(query.toString(), subtitle.getLanguageCode(), isAuto(subtitle) ? ClientCaptionTrack.KIND_AUTO : ClientCaptionTrack.KIND_MANUAL, name, original);
    }

    private static boolean isAuto(MediaSubtitle subtitle) {
        return TYPE_ASR.equals(subtitle.getType()) || (subtitle.getVssId() != null && subtitle.getVssId().startsWith(VSS_AUTO_PREFIX));
    }

    private static String baseOf(@Nullable String language) {
        if (language == null) {
            return "";
        }

        String lower = language.toLowerCase(Locale.ROOT).replace('_', '-');
        int dash = lower.indexOf('-');
        return dash < 0 ? lower : lower.substring(0, dash);
    }

    @Nullable
    private static String download(String url) throws IOException {
        try (Response response = OkHttpManager.instance().doGetRequest(url, Collections.singletonMap("User-Agent", DefaultHeaders.APP_USER_AGENT))) {
            if (response == null || !response.isSuccessful() || response.body() == null) {
                throw new IOException("HTTP " + (response == null ? "none" : response.code()));
            }

            try (InputStream stream = response.body().byteStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] chunk = new byte[CHUNK_BYTES];
                int read;

                while ((read = stream.read(chunk)) != -1) {
                    out.write(chunk, 0, read);

                    if (out.size() > MAX_TRACK_BYTES) {
                        return null;
                    }
                }

                return new String(out.toByteArray(), StandardCharsets.UTF_8);
            }
        }
    }
}
