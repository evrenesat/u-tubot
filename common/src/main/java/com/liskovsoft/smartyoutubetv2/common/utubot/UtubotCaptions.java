package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.net.Uri;

import androidx.annotation.Nullable;

import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.Format;
import com.google.android.exoplayer2.source.MediaSource;
import com.google.android.exoplayer2.source.MergingMediaSource;
import com.google.android.exoplayer2.source.SingleSampleMediaSource;
import com.google.android.exoplayer2.upstream.DefaultHttpDataSourceFactory;
import com.google.android.exoplayer2.util.MimeTypes;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The HQ captions of the backend as external WebVTT tracks merged into the media source of the player. The tracks show up in the
 * subtitle picker as "u·tubot: label" (see TrackSelectorUtil).
 */
public final class UtubotCaptions {
    public static final String TRACK_ID_PREFIX = "utubot:";
    private static final String AUTHORIZATION_HEADER = "Authorization";
    private static final String USER_AGENT = "u-tubot";
    private static final Map<String, String> sTrackNames = new ConcurrentHashMap<>();

    private UtubotCaptions() {
    }

    public static boolean isCaptionTrack(@Nullable Format format) {
        return format != null && format.id != null && format.id.startsWith(TRACK_ID_PREFIX);
    }

    /**
     * The name of an HQ caption track in the picker, null for any other track
     */
    @Nullable
    public static String getTrackName(@Nullable String formatId) {
        return formatId != null ? sTrackNames.get(formatId) : null;
    }

    /**
     * @return the source with the ready captions of the video merged in, the same source when it has none
     */
    public static MediaSource attach(Context context, MediaSource source, @Nullable String videoId) {
        if (videoId == null || !UtubotSettings.instance(context).isConfigured()) {
            return source;
        }

        Captions captions = UtubotManager.instance(context).getCachedCaptions(videoId);

        if (captions == null || !captions.isReady()) {
            return source;
        }

        UtubotClient client = UtubotManager.instance(context).newClient();
        List<MediaSource> sources = new ArrayList<>();
        sources.add(source);

        for (CaptionTrack track : captions.tracks) {
            sources.add(trackSource(context, client, videoId, track));
        }

        return new MergingMediaSource(sources.toArray(new MediaSource[0]));
    }

    private static MediaSource trackSource(Context context, UtubotClient client, String videoId, CaptionTrack track) {
        String id = trackId(videoId, track);
        sTrackNames.put(id, context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.utubot_caption_prefix, track.label));
        Format format = Format.createTextSampleFormat(id, MimeTypes.TEXT_VTT, 0, track.lang);
        String url = client.captionUrl(track.url);
        DefaultHttpDataSourceFactory factory = new DefaultHttpDataSourceFactory(USER_AGENT);
        String authorization = client.authorizationFor(url);

        if (authorization != null) {
            factory.getDefaultRequestProperties().set(AUTHORIZATION_HEADER, authorization);
        }

        return new SingleSampleMediaSource.Factory(factory).createMediaSource(Uri.parse(url), format, C.TIME_UNSET);
    }

    static String trackId(String videoId, CaptionTrack track) {
        return TRACK_ID_PREFIX + videoId + ":" + track.lang;
    }
}
