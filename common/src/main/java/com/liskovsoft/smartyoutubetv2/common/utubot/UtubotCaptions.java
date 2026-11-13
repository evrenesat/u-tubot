package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.net.Uri;

import androidx.annotation.Nullable;

import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.Format;
import com.google.android.exoplayer2.source.MediaSource;
import com.google.android.exoplayer2.source.MergingMediaSource;
import com.google.android.exoplayer2.source.SingleSampleMediaSource;
import com.google.android.exoplayer2.upstream.DefaultDataSourceFactory;
import com.google.android.exoplayer2.upstream.DefaultHttpDataSourceFactory;
import com.google.android.exoplayer2.util.MimeTypes;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCaptionStore.StoredTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The HQ captions of the backend as external WebVTT tracks merged into the media source of the player: the files the TV stored (see
 * UtubotCaptionStore) and, until they are stored, the backend's. The tracks show up in the subtitle picker as "u·tubot: label" (see
 * TrackSelectorUtil).
 */
public final class UtubotCaptions {
    public static final String TRACK_ID_PREFIX = "utubot:";
    private static final String AUTHORIZATION_HEADER = "Authorization";
    private static final String USER_AGENT = "u-tubot";
    private static final Map<String, String> sTrackNames = new ConcurrentHashMap<>();

    private UtubotCaptions() {
    }

    public static boolean isCaptionTrack(@Nullable Format format) {
        return format != null && isCaptionTrackId(format.id);
    }

    public static boolean isCaptionTrackId(@Nullable String formatId) {
        return formatId != null && formatId.startsWith(TRACK_ID_PREFIX);
    }

    /**
     * Whether the track is one of the HQ captions of this video. The id is "utubot:VIDEO:LANG", so the track of the video played
     * before does not count.
     */
    public static boolean isCaptionTrackOf(@Nullable String formatId, @Nullable String videoId) {
        return videoId != null && formatId != null && formatId.startsWith(TRACK_ID_PREFIX + videoId + ":");
    }

    /**
     * Two subtitle tracks of the same language are the same pick only when both come from the same side: an HQ track of the
     * backend next to a track of YouTube in that language is another choice.
     */
    public static boolean isSameSource(@Nullable String formatId, @Nullable String otherFormatId) {
        return isCaptionTrackId(formatId) == isCaptionTrackId(otherFormatId);
    }

    /**
     * Whether the saved subtitle choice of the user (see VideoStateController#restoreSubtitleFormat) may replace what is selected.
     * It may not when what is selected is the HQ track of this video: that pick (the automatic one, or the one the user asked the
     * backend for) comes after the saved choice, which is usually "no subtitles", and must not lose to it.
     */
    public static boolean mayRestoreSavedChoice(@Nullable String selectedFormatId, @Nullable String videoId) {
        return !isCaptionTrackOf(selectedFormatId, videoId);
    }

    /**
     * Whether the HQ track is selected once the captions are there. At the start of the video the setting "Select HQ captions
     * automatically" decides; captions the user asked for are selected whatever it says.
     */
    public static boolean shouldSelect(boolean autoSelectEnabled, boolean requestedByUser) {
        return requestedByUser || autoSelectEnabled;
    }

    /**
     * The name of an HQ caption track in the picker, null for any other track
     */
    @Nullable
    public static String getTrackName(@Nullable String formatId) {
        return formatId != null ? sTrackNames.get(formatId) : null;
    }

    /**
     * @return the source with the HQ captions of the video merged in: the files stored on the TV (whatever the backend says, even
     * without it), and the tracks the backend answered with that are not stored yet. The same source when there are none.
     */
    public static MediaSource attach(Context context, MediaSource source, @Nullable String videoId) {
        if (videoId == null) {
            return source;
        }

        List<MediaSource> sources = new ArrayList<>();
        sources.add(source);
        Set<String> stored = new HashSet<>();

        for (StoredTrack track : UtubotCaptionStore.instance(context).tracks(videoId)) {
            sources.add(storedTrackSource(context, videoId, track));
            stored.add(track.lang);
        }

        if (UtubotSettings.instance(context).isConfigured()) {
            Captions captions = UtubotManager.instance(context).getCachedCaptions(videoId);

            if (captions != null && captions.isReady()) {
                UtubotClient client = UtubotManager.instance(context).newClient();

                for (CaptionTrack track : captions.tracks) {
                    if (!stored.contains(track.lang)) {
                        sources.add(remoteTrackSource(context, client, videoId, track));
                    }
                }
            }
        }

        return sources.size() > 1 ? new MergingMediaSource(sources.toArray(new MediaSource[0])) : source;
    }

    private static MediaSource storedTrackSource(Context context, String videoId, StoredTrack track) {
        Format format = trackFormat(context, videoId, track.lang, track.label);

        return new SingleSampleMediaSource.Factory(new DefaultDataSourceFactory(context, USER_AGENT))
                .createMediaSource(Uri.fromFile(track.file), format, C.TIME_UNSET);
    }

    private static MediaSource remoteTrackSource(Context context, UtubotClient client, String videoId, CaptionTrack track) {
        Format format = trackFormat(context, videoId, track.lang, track.label);
        String url = client.captionUrl(track.url);
        DefaultHttpDataSourceFactory factory = new DefaultHttpDataSourceFactory(USER_AGENT);
        String authorization = client.authorizationFor(url);

        if (authorization != null) {
            factory.getDefaultRequestProperties().set(AUTHORIZATION_HEADER, authorization);
        }

        return new SingleSampleMediaSource.Factory(factory).createMediaSource(Uri.parse(url), format, C.TIME_UNSET);
    }

    private static Format trackFormat(Context context, String videoId, String lang, String label) {
        String id = trackId(videoId, lang);
        sTrackNames.put(id, context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.utubot_caption_prefix, label));

        return Format.createTextSampleFormat(id, MimeTypes.TEXT_VTT, 0, lang);
    }

    static String trackId(String videoId, CaptionTrack track) {
        return trackId(videoId, track.lang);
    }

    static String trackId(String videoId, String lang) {
        return TRACK_ID_PREFIX + videoId + ":" + lang;
    }
}
