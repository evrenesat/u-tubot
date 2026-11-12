package com.liskovsoft.smartyoutubetv2.common.exoplayer.controller;

import android.content.Context;
import android.os.Build;
import android.os.Build.VERSION;
import android.os.SystemClock;
import android.view.Surface;

import androidx.annotation.Nullable;

import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.ExoPlaybackException;
import com.google.android.exoplayer2.Format;
import com.google.android.exoplayer2.PlaybackParameters;
import com.google.android.exoplayer2.Player;
import com.google.android.exoplayer2.SimpleExoPlayer;
import com.google.android.exoplayer2.analytics.AnalyticsListener;
import com.google.android.exoplayer2.audio.AudioClockInfo;
import com.google.android.exoplayer2.decoder.DecoderCounters;
import com.google.android.exoplayer2.source.MediaSourceEventListener.LoadEventInfo;
import com.google.android.exoplayer2.source.MediaSourceEventListener.MediaLoadData;
import com.google.android.exoplayer2.source.MediaSource;
import com.google.android.exoplayer2.source.MergingMediaSource;
import com.google.android.exoplayer2.source.TrackGroupArray;
import com.google.android.exoplayer2.trackselection.DefaultTrackSelector;
import com.google.android.exoplayer2.trackselection.TrackSelection;
import com.google.android.exoplayer2.trackselection.TrackSelectionArray;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemFormatInfo;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCaptions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.BuildConfig;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.FormatAttempts;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.LastState;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.PlaybackHealth;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.PlayerCommands;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.PlayerFailure;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.SilenceDetector;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.VideoStarts;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.ExoMediaSourceFactory;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.errors.TrackErrorFixer;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.CensoredWords.Range;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.FrameStepper;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.RangeMuter;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.VolumeBooster;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.ExoFormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.TrackInfoFormatter2;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.TrackSelectorManager;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.TrackSelectorUtil;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.track.MediaTrack;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.track.VideoTrack;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.versions.ExoUtils;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.versions.renderer.DebugInfoMediaCodecVideoRenderer;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import org.json.JSONArray;

import java.io.InputStream;
import java.lang.ref.WeakReference;
import java.util.List;

public class ExoPlayerController implements Player.EventListener {
    private static final String TAG = ExoPlayerController.class.getSimpleName();
    private final Context mContext;
    private final ExoMediaSourceFactory mMediaSourceFactory;
    private boolean mUtubotCaptionsSelectPending;
    private final TrackSelectorManager mTrackSelectorManager;
    private final TrackInfoFormatter2 mTrackFormatter;
    private final TrackErrorFixer mTrackErrorFixer;
    private final FrameStepper mFrameStepper;
    private final RangeMuter mRangeMuter;
    private boolean mOnSourceChanged;
    private WeakReference<Video> mVideo;
    private final PlayerEventListener mEventListener;
    private SimpleExoPlayer mPlayer;
    private PlayerView mPlayerView;
    private VolumeBooster mVolumeBooster;
    private boolean mIsEnded;
    private Runnable mOnVideoLoaded;
    // The volume set, kept while the range muter has the sound off
    private float mVolume = 1f;
    private boolean mIsMuted;
    private final PlaybackHealth mHealth = new PlaybackHealth();
    @Nullable
    private AudioClockInfo mAudioClockInfo;
    private final Runnable mHealthCheck = this::checkHealth;
    /**
     * It played since the player was prepared with its source: playing again is a resume (see PlaybackHealth#onResumed), not the start
     */
    private boolean mHasPlayedSource;
    /**
     * The video has a surface to be shown on. Without one (e.g. the sound plays on in the background) no frame is rendered.
     */
    private boolean mHasSurface;
    /**
     * Of the player set (see setVideoRenderer): the frames it decoded to reach a position
     */
    @Nullable
    private DebugInfoMediaCodecVideoRenderer mVideoRenderer;
    /**
     * How the formats tried do (see FormatAttempts): a frame shown means the video works, plus the decoders, the frames dropped
     * and the throughput of the segments
     */
    private final AnalyticsListener mDiagnosticsListener = new AnalyticsListener() {
        @Override
        public void onRenderedFirstFrame(EventTime eventTime, @Nullable Surface surface) {
            FormatAttempts.onVideoRendered();
            VideoStarts.onFirstFrame(getFirstFrame());
        }

        @Override
        public void onSurfaceSizeChanged(EventTime eventTime, int width, int height) {
            // 0x0 is none. A surface of a size not known yet is -1x-1.
            mHasSurface = width != 0 || height != 0;
        }

        @Override
        public void onDecoderInitialized(EventTime eventTime, int trackType, String decoderName, long initializationDurationMs) {
            if (trackType == C.TRACK_TYPE_VIDEO || trackType == C.TRACK_TYPE_AUDIO) {
                FormatAttempts.onDecoder(trackType == C.TRACK_TYPE_VIDEO, decoderName);
                VideoStarts.onDecoder(trackType == C.TRACK_TYPE_VIDEO, decoderName, initializationDurationMs);
            }
        }

        @Override
        public void onDroppedVideoFrames(EventTime eventTime, int droppedFrames, long elapsedMs) {
            FormatAttempts.onDroppedFrames(droppedFrames);
        }

        @Override
        public void onLoadStarted(EventTime eventTime, LoadEventInfo loadEventInfo, MediaLoadData mediaLoadData) {
            // Asked of, here: one that never answers has a server too. Not the subtitles': their server isn't the video's.
            if (isTimedLoad(mediaLoadData) && (isVideoLoad(mediaLoadData) || mediaLoadData.trackType == C.TRACK_TYPE_AUDIO)) {
                FormatAttempts.onRequest(loadEventInfo.uri != null ? loadEventInfo.uri.getHost() : null);
            }

            if (isTimedLoad(mediaLoadData)) {
                VideoStarts.onLoadStarted(mediaLoadData.dataType == C.DATA_TYPE_MEDIA_INITIALIZATION, isVideoLoad(mediaLoadData),
                        mediaLoadData.trackType == C.TRACK_TYPE_AUDIO, loadEventInfo.elapsedRealtimeMs);
            }
        }

        @Override
        public void onLoadCompleted(EventTime eventTime, LoadEventInfo loadEventInfo, MediaLoadData mediaLoadData) {
            if (mediaLoadData.dataType == C.DATA_TYPE_MEDIA) {
                FormatAttempts.onLoad(loadEventInfo.bytesLoaded, loadEventInfo.loadDurationMs, isVideoLoad(mediaLoadData),
                        mediaLoadData.trackType == C.TRACK_TYPE_AUDIO, mediaLoadData.mediaEndTimeMs);
            }

            if (isTimedLoad(mediaLoadData)) {
                VideoStarts.onLoad(mediaLoadData.dataType == C.DATA_TYPE_MEDIA_INITIALIZATION, isVideoLoad(mediaLoadData),
                        mediaLoadData.trackType == C.TRACK_TYPE_AUDIO, loadEventInfo.elapsedRealtimeMs - loadEventInfo.loadDurationMs,
                        loadEventInfo.elapsedRealtimeMs, loadEventInfo.bytesLoaded);
            }
        }

        /**
         * A segment of the media or its initialization (see VideoStarts)
         */
        private boolean isTimedLoad(MediaLoadData mediaLoadData) {
            return mediaLoadData.dataType == C.DATA_TYPE_MEDIA || mediaLoadData.dataType == C.DATA_TYPE_MEDIA_INITIALIZATION;
        }

        /**
         * Muxed (e.g. the URL list's) is video too
         */
        private boolean isVideoLoad(MediaLoadData mediaLoadData) {
            return mediaLoadData.trackType == C.TRACK_TYPE_VIDEO || mediaLoadData.trackType == C.TRACK_TYPE_DEFAULT;
        }
    };

    public ExoPlayerController(Context context, PlayerEventListener eventListener) {
        PlayerTweaksData playerTweaksData = PlayerTweaksData.instance(context);
        mContext = context.getApplicationContext();
        mMediaSourceFactory = new ExoMediaSourceFactory(context);
        mTrackSelectorManager = new TrackSelectorManager(context);
        mTrackFormatter = new TrackInfoFormatter2();
        mTrackFormatter.enableBitrate(PlayerTweaksData.instance(context).isQualityInfoBitrateEnabled());
        mTrackErrorFixer = new TrackErrorFixer(mTrackSelectorManager);
        mTrackErrorFixer.setOnHttpError(this::onHttpError);
        mFrameStepper = new FrameStepper(this::onFramePositionChanged);
        mRangeMuter = new RangeMuter(this::onMuteChanged);

        mMediaSourceFactory.setTrackErrorFixer(mTrackErrorFixer);
        mEventListener = eventListener;
        
        applyShield720pFix();
        VideoTrack.sIsAltPresetsEnabled = playerTweaksData.isAltPresetsEnabled();
        MediaTrack.setAvcOverVp9Preferred(playerTweaksData.isAvcOverVp9Preferred());
        TrackSelectorUtil.setVoiceBoostMark(context.getString(R.string.audio_voice_boost));
    }

    /**
     * To the player failure log: ExoPlayer retries the segment, a fatal one comes again as an engine error
     */
    private void onHttpError(int responseCode, String track, @Nullable Format failed, boolean switched) {
        PlayerFailure failure = PlayerFailure.create(mContext, PlayerFailure.KIND_TRACK_LOAD_ERROR)
                .video(getVideo())
                .http(responseCode, track, failed);

        if (mPlayer != null) {
            failure.position(mPlayer.getCurrentPosition(), mPlayer.getDuration());
        }

        if (switched) {
            failure.action("select_other_codec");

            // Given up on: ExoPlayer retries the segments of one it hasn't
            if (!"other".equals(track)) {
                FormatAttempts.onStreamFailed("video".equals(track));
            }
        }

        failure.record();
    }

    /**
     * The failures that throw no error (see PlaybackHealth): the video never shows or freezes, frames drop, it stalls again and
     * again, the sound is silent
     */
    private void checkHealth() {
        if (mPlayer == null) {
            return;
        }

        try {
            PlaybackHealth.Sample sample = new PlaybackHealth.Sample();
            sample.nowMs = SystemClock.elapsedRealtime();
            sample.attempt = FormatAttempts.getAttemptId();
            sample.videoId = FormatAttempts.getVideoId();
            sample.isPlaying = mPlayer.getPlayWhenReady() && mPlayer.getPlaybackState() == Player.STATE_READY;
            sample.positionMs = mPlayer.getCurrentPosition();
            // Not shown, the video isn't checked
            sample.hasVideo = mPlayer.getVideoFormat() != null && mHasSurface;
            sample.hasAudio = mPlayer.getAudioFormat() != null;
            sample.isMuted = mIsMuted || mPlayer.getVolume() == 0;
            sample.silentMs = SilenceDetector.getSilentMs();
            sample.soundBuffers = SilenceDetector.getSoundBuffers();
            sample.stalls = FormatAttempts.getStalls();
            sample.stallMs = FormatAttempts.getStallMs();
            sample.playedMs = FormatAttempts.getPlayedMs();

            if (mAudioClockInfo != null) {
                sample.audioTimestampState = mAudioClockInfo.timestampState;
                sample.audioPlayheadMs = mAudioClockInfo.playheadMs;
                sample.audioLatencyMs = mAudioClockInfo.latencyMs;
                sample.audioLongestHoldMs = mAudioClockInfo.longestHoldMs;
                sample.audioTotalFramesMismatches = mAudioClockInfo.totalFramesMismatches;
                sample.audioTotalClockMismatches = mAudioClockInfo.totalClockMismatches;
                sample.audioTotalHoldReleases = mAudioClockInfo.totalHoldReleases;
            }

            DecoderCounters counters = mPlayer.getVideoDecoderCounters();

            if (counters != null) {
                counters.ensureUpdated();

                // Unknown, not none: a tunneled decoder that doesn't report each frame it shows (see isRenderedCountKnown)
                if (mVideoRenderer == null || mVideoRenderer.isRenderedCountKnown()) {
                    sample.renderedFrames = counters.renderedOutputBufferCount;
                    sample.droppedFrames = counters.droppedBufferCount;
                    sample.droppedToKeyframes = counters.droppedToKeyframeCount;
                }

                sample.inputBuffers = counters.inputBufferCount;
            }

            // The renderer goes on with the same video when only the audio is switched: its first frame isn't rendered again.
            // Its counters start over each time it's enabled, so frames rendered are of the format tried.
            if (sample.hasVideo && sample.renderedFrames > 0 && !FormatAttempts.isVideoRendered()) {
                FormatAttempts.onVideoRendered();
            }

            sample.isVideoRendered = FormatAttempts.isVideoRendered();

            for (String kind : mHealth.onSample(sample)) {
                recordHealthFailure(kind, sample);
            }

            long soundBackMs = mHealth.takeSoundBackMs();

            if (soundBackMs >= 0) {
                FormatAttempts.onSoundBack(soundBackMs);
            }

            onStartFrames(mHealth.takeStartFrames());
            // For an app exit to tell (see AppExits)
            LastState.onPlayer(mContext, true, sample.isPlaying);
        } catch (RuntimeException e) {
            Log.e(TAG, "Can't check the playback: " + e.getMessage());
        } finally {
            if (mPlayer != null) {
                Utils.postDelayed(mHealthCheck, mHealth.getTickMs());
            }
        }
    }

    private void recordHealthFailure(String kind, PlaybackHealth.Sample sample) {
        PlayerFailure failure = PlayerFailure.create(mContext, kind)
                .video(getVideo())
                .position(sample.positionMs, mPlayer.getDuration())
                .formats(getVideoFormat(), getAudioFormat())
                .source(FormatAttempts.getClient(), FormatAttempts.getProtocol())
                .detail("renderedFrames", sample.renderedFrames)
                .detail("droppedFrames", sample.droppedFrames)
                .detail("droppedToKeyframes", sample.droppedToKeyframes)
                .detail("inputBuffers", sample.inputBuffers)
                .detail("bufferedMs", mPlayer.getBufferedPosition() - sample.positionMs)
                .detail("silentMs", sample.silentMs)
                .detail("stalls", sample.stalls)
                .detail("stallMs", sample.stallMs)
                .detail("playedMs", sample.playedMs);

        if (PlaybackHealth.KIND_START_FROZEN.equals(kind)) {
            failure.detail("frozenMs", mHealth.getStartFrozenMs());
            failure.detail("clockStill", mHealth.isStartClockStill());
        }

        if (PlaybackHealth.KIND_START_FROZEN.equals(kind) || PlaybackHealth.KIND_FRAME_DROPS.equals(kind)) {
            JSONArray trail = toJson(mHealth.getStartTrail());

            if (trail.length() > 0) {
                failure.detail("startTrail", trail);
            }

            // Past the start too: the audio clock starts over after a seek, a pause or buffering
            JSONArray resumeTrail = toJson(mHealth.getResumeTrail());

            if (resumeTrail.length() > 0) {
                failure.detail("resumeTrail", resumeTrail);
                failure.detail("resumedBy", mHealth.getResumedBy());
            }

            if (mAudioClockInfo != null) {
                failure.detail("audioFramesMismatches", mAudioClockInfo.framesMismatches);
                failure.detail("audioClockMismatches", mAudioClockInfo.clockMismatches);
                failure.detail("audioBadLatencies", mAudioClockInfo.badLatencies);
                failure.detail("audioHoldReleases", mAudioClockInfo.holdReleases);
                failure.detail("audioLongestHoldMs", mAudioClockInfo.longestHoldMs);
            }
        }

        // The stream that didn't work: frame drops and stalls play, worse
        if (PlaybackHealth.KIND_NO_VIDEO.equals(kind) || PlaybackHealth.KIND_VIDEO_FROZEN.equals(kind)) {
            FormatAttempts.onStreamFailed(true);
        } else if (PlaybackHealth.KIND_AUDIO_SILENT.equals(kind) && PlaybackHealth.isSilentFromStart(sample)) {
            FormatAttempts.onStreamFailed(false);
        }

        failure.record();
    }

    /**
     * The first play since the source was prepared is the start. Past it, a play is after a seek, a pause or buffering: its audio
     * clock started over, the seconds from here are sampled closely as the start's are.
     */
    private void onHealthPlaying() {
        if (!mHasPlayedSource) {
            mHasPlayedSource = true;
            mHealth.onStarted();
            return;
        }

        mHealth.onResumed(SystemClock.elapsedRealtime());

        if (mPlayer != null) {
            // Where it is as it plays again: the trail's first sample
            Utils.removeCallbacks(mHealthCheck);
            Utils.postDelayed(mHealthCheck, 0);
        }
    }

    private static void onStartFrames(@Nullable PlaybackHealth.StartFrames frames) {
        if (frames != null) {
            VideoStarts.onFrames(frames);
        }
    }

    private static JSONArray toJson(List<long[]> rows) {
        JSONArray result = new JSONArray();

        for (long[] row : rows) {
            JSONArray item = new JSONArray();

            for (long value : row) {
                item.put(value);
            }

            result.put(item);
        }

        return result;
    }

    private void applyShield720pFix() {
        PlayerData playerData = PlayerData.instance(mContext);
        mTrackSelectorManager.selectTrack(FormatItem.toMediaTrack(playerData.getFormat(FormatItem.TYPE_VIDEO)));
        mTrackSelectorManager.selectTrack(FormatItem.toMediaTrack(playerData.getFormat(FormatItem.TYPE_AUDIO)));
        mTrackSelectorManager.selectTrack(FormatItem.toMediaTrack(playerData.getFormat(FormatItem.TYPE_SUBTITLE)));
    }

    public void openSabr(MediaItemFormatInfo formatInfo) {
        MediaSource mediaSource = mMediaSourceFactory.fromSabrFormatInfo(formatInfo);
        openMediaSource(mediaSource);
    }

    public void openDash(MediaItemFormatInfo formatInfo) {
        MediaSource mediaSource = mMediaSourceFactory.fromDashFormatInfo(formatInfo);
        openMediaSource(mediaSource);
    }

    public void openDash(InputStream dashManifest) {
        MediaSource mediaSource = mMediaSourceFactory.fromDashManifest(dashManifest);
        openMediaSource(mediaSource);
    }

    public void openDashUrl(String dashManifestUrl) {
        MediaSource mediaSource = mMediaSourceFactory.fromDashManifestUrl(dashManifestUrl);
        openMediaSource(mediaSource);
    }

    public void openHlsUrl(String hlsPlaylistUrl) {
        MediaSource mediaSource = mMediaSourceFactory.fromHlsPlaylist(hlsPlaylistUrl);
        openMediaSource(mediaSource);
    }

    public void openUrlList(List<String> urlList) {
        MediaSource mediaSource = mMediaSourceFactory.fromUrlList(urlList);
        openMediaSource(mediaSource);
    }

    public void openMerged(MediaItemFormatInfo formatInfo, String hlsPlaylistUrl) {
        MediaSource dashMediaSource = mMediaSourceFactory.fromDashFormatInfo(formatInfo);
        MediaSource hlsMediaSource = mMediaSourceFactory.fromHlsPlaylist(hlsPlaylistUrl);
        openMediaSource(new MergingMediaSource(dashMediaSource, hlsMediaSource));
    }

    public void openMerged(InputStream dashManifest, String hlsPlaylistUrl) {
        MediaSource dashMediaSource = mMediaSourceFactory.fromDashManifest(dashManifest);
        MediaSource hlsMediaSource = mMediaSourceFactory.fromHlsPlaylist(hlsPlaylistUrl);
        openMediaSource(new MergingMediaSource(dashMediaSource, hlsMediaSource));
    }

    private void openMediaSource(MediaSource mediaSource) {
        mFrameStepper.reset();
        mRangeMuter.reset();
        resetPlayerState(); // fixes occasional video artifacts and problems with quality switching
        setQualityInfo("");

        boolean isMerged = mediaSource instanceof MergingMediaSource;
        mediaSource = attachUtubotCaptions(mediaSource);
        mTrackSelectorManager.setMergedSource(isMerged);
        mTrackSelectorManager.invalidate();
        mOnSourceChanged = true;
        mEventListener.onSourceChanged(getVideo());
        VideoStarts.onPrepare();
        FormatAttempts.onPrepare();
        mHasPlayedSource = false;
        mPlayer.prepare(mediaSource);
        // Its first seconds are looked at closely: the check may be 2 s away, past its first frame
        Utils.removeCallbacks(mHealthCheck);
        Utils.postDelayed(mHealthCheck, PlaybackHealth.START_TICK_MS);
    }

    /**
     * The HQ captions of the backend, when they were fetched in time (see setVideo). Not in the merged live sources: their tracks
     * are filtered by codec and bitrate, which a text track has none of.
     */
    private MediaSource attachUtubotCaptions(MediaSource mediaSource) {
        Video video = getVideo();

        if (!UtubotSettings.isBuiltIn() || video == null || mediaSource instanceof MergingMediaSource) {
            return mediaSource;
        }

        MediaSource merged = UtubotCaptions.attach(mContext, mediaSource, video.videoId);
        mUtubotCaptionsSelectPending = merged != mediaSource && UtubotSettings.instance(mContext).isAutoCaptionsEnabled();
        return merged;
    }

    /**
     * Selects the HQ captions track once the tracks are there, when it's set to
     */
    private void selectUtubotCaptions() {
        if (!mUtubotCaptionsSelectPending) {
            return;
        }

        mUtubotCaptionsSelectPending = false;

        for (MediaTrack track : mTrackSelectorManager.getSubtitleTracks()) {
            if (UtubotCaptions.isCaptionTrack(track.format)) {
                mTrackSelectorManager.selectTrack(track);
                return;
            }
        }
    }

    public long getPositionMs() {
        if (mPlayer == null) {
            return -1;
        }

        long framePositionMs = mFrameStepper.getPositionMs();

        return framePositionMs != -1 ? framePositionMs : mPlayer.getCurrentPosition();
    }

    /**
     * NOTE: Pos gathered from content block data may slightly exceed video duration
     * (e.g. 302200 when duration is 302000).
     */
    public void setPositionMs(long positionMs) {
        // Url list videos at load stage has undefined (-1) length. So, we need to remove length check.
        if (mPlayer != null && positionMs >= 0 && positionMs <= getDurationMs()) {
            PlayerCommands.onSeek(PlayerCommands.SOURCE_APP, positionMs);
            VideoStarts.onSeek(positionMs);
            mPlayer.seekTo(positionMs);
        }
    }

    public long getBufferedPositionMs() {
        return mPlayer != null ? mPlayer.getBufferedPosition() : -1;
    }

    public long getDurationMs() {
        if (mPlayer == null) {
            return -1;
        }

        long duration = mPlayer.getDuration();
        return duration != C.TIME_UNSET ? duration : -1;
    }

    public void setPlayWhenReady(boolean play) {
        if (mPlayer != null) {
            if (mPlayer.getPlayWhenReady() != play) {
                PlayerCommands.onPlayWhenReady(play, PlayerCommands.SOURCE_APP, mPlayer.getCurrentPosition());
            }

            mPlayer.setPlayWhenReady(play);
        }
    }

    public boolean getPlayWhenReady() {
        if (mPlayer == null) {
            return false;
        }

        return mPlayer.getPlayWhenReady();
    }

    public boolean isPlaying() {
        return ExoUtils.isPlaying(mPlayer);
    }
    
    public boolean isLoading() {
        return ExoUtils.isLoading(mPlayer);
    }

    public boolean isBuffering() {
        return ExoUtils.isBuffering(mPlayer);
    }
    
    public boolean containsMedia() {
        if (mPlayer == null) {
            return false;
        }

        return mPlayer.getPlaybackState() != Player.STATE_IDLE;
    }
    
    public void release() {
        mTrackSelectorManager.release();
        mMediaSourceFactory.release();
        releasePlayer();
        mPlayerView = null;
        // Don't destroy it (needed inside the bridge)!
        //mEventListener = null;
    }
    
    public void setPlayer(SimpleExoPlayer player) {
        mPlayer = player;
        player.addListener(this);
        // Set by the view after this (see onSurfaceSizeChanged)
        mHasSurface = false;
        player.addAnalyticsListener(mDiagnosticsListener);
        Utils.postDelayed(mHealthCheck, mHealth.getTickMs());
        mRangeMuter.setPlayer(player);
    }

    /**
     * Enables {@link #nextFrame()}. Pass the video renderer of the player set with {@link #setPlayer(SimpleExoPlayer)}.
     */
    public void setVideoRenderer(DebugInfoMediaCodecVideoRenderer renderer) {
        mFrameStepper.setPlayer(mPlayer, renderer);
        mVideoRenderer = renderer;
    }

    /**
     * Where the video starts (e.g. a resume's position) and what with, and the frames decoded first to get there
     */
    private VideoStarts.FirstFrame getFirstFrame() {
        DebugInfoMediaCodecVideoRenderer renderer = mVideoRenderer;

        return VideoStarts.FirstFrame.of(mPlayer != null ? mPlayer.getCurrentPosition() : -1, mPlayer != null ? mPlayer.getVideoFormat() : null,
                renderer != null ? renderer.getSkippedToPosition() : 0, renderer != null ? renderer.getSkipStartMs() : -1);
    }

    /**
     * For the diagnostics (see #checkHealth). Pass the one of the player set with {@link #setPlayer(SimpleExoPlayer)}.
     */
    public void setAudioClockInfo(@Nullable AudioClockInfo audioClockInfo) {
        mAudioClockInfo = audioClockInfo;
    }

    /**
     * Pauses (if playing) and shows the next frame. Live streams aren't stepped.
     */
    public void nextFrame() {
        if (getVideo() != null && getVideo().isLive) {
            return;
        }

        mFrameStepper.stepForward();
    }

    //@Override
    //public void setEventListener(PlayerEventListener eventListener) {
    //    mEventListener = eventListener;
    //}
    
    public void setPlayerView(PlayerView playerView) {
        mPlayerView = playerView;
    }
    
    public void setTrackSelector(DefaultTrackSelector trackSelector) {
        mTrackSelectorManager.setTrackSelector(trackSelector);

        if (mContext != null && trackSelector != null && PlayerTweaksData.instance(mContext).isTunneledPlaybackEnabled()) {
            // Enable tunneling if supported by the current media and device configuration.
            if (VERSION.SDK_INT >= 21) {
                trackSelector.setParameters(trackSelector.buildUponParameters().setTunnelingAudioSessionId(C.generateAudioSessionIdV21(mContext)));
            }
        }
    }
    
    public void setVideo(Video video) {
        mVideo = new WeakReference<>(video);

        if (UtubotSettings.isBuiltIn() && video != null) {
            UtubotManager.instance(mContext).prefetchCaptions(video.videoId);
        }
    }
    
    public Video getVideo() {
        return mVideo != null ? mVideo.get() : null;
    }
    
    public List<FormatItem> getVideoFormats() {
        return ExoFormatItem.from(mTrackSelectorManager.getVideoTracks());
    }
    
    public List<FormatItem> getAudioFormats() {
        return ExoFormatItem.from(mTrackSelectorManager.getAudioTracks());
    }
    
    public List<FormatItem> getSubtitleFormats() {
        return ExoFormatItem.from(mTrackSelectorManager.getSubtitleTracks());
    }
    
    public void selectFormat(FormatItem formatItem) {
        if (formatItem != null && formatItem.getTrack() != null) {
            FormatItem selectedFormatItem = getSelectedFormat(formatItem.getTrack().rendererIndex);
            if (!formatItem.equals(selectedFormatItem)) {
                mTrackSelectorManager.selectTrack(formatItem.getTrack());
                mEventListener.onTrackSelected(formatItem);
            }
        }
    }

    public FormatItem getVideoFormat() {
        return getSelectedFormat(TrackSelectorManager.RENDERER_INDEX_VIDEO);
    }

    public FormatItem getAudioFormat() {
        return getSelectedFormat(TrackSelectorManager.RENDERER_INDEX_AUDIO);
    }

    public FormatItem getSubtitleFormat() {
        return getSelectedFormat(TrackSelectorManager.RENDERER_INDEX_SUBTITLE);
    }

    private FormatItem getSelectedFormat(int rendererIndex) {
        return ExoFormatItem.from(mTrackSelectorManager.getSelectedTrack(rendererIndex));
    }

    @Override
    public void onTracksChanged(TrackGroupArray trackGroups, TrackSelectionArray trackSelections) {
        Log.d(TAG, "onTracksChanged: start: groups length: " + trackGroups.length);

        if (trackGroups.length == 0) {
            Log.i(TAG, "onTracksChanged: Hmm. Strange. Received empty groups, no selections. Why is this happens only on next/prev videos?");
            return;
        }

        notifyOnVideoLoad();
        selectUtubotCaptions();

        for (TrackSelection selection : trackSelections.getAll()) {
            if (selection != null) {
                // EXO: 2.12.1
                //Format format = selection.getSelectedFormat();

                // EXO: 2.13.1
                Format format = selection.getFormat(0);

                mEventListener.onTrackChanged(ExoFormatItem.from(format));

                mTrackFormatter.setFormat(format);
            }
        }
        
        setQualityInfo(mTrackFormatter.getQualityLabel());

        // Manage audio focus. E.g. use Spotify when audio is disabled. (NOT NEEDED!!!)
        //MediaTrack audioTrack = mTrackSelectorManager.getAudioTrack();
        //ExoPlayerInitializer.enableAudioFocus(mPlayer, audioTrack != null && !audioTrack.isEmpty());
    }

    private void notifyOnVideoLoad() {
        if (mOnSourceChanged) {
            mOnSourceChanged = false;

            mEventListener.onVideoLoaded(getVideo());

            if (mOnVideoLoaded != null) {
                mOnVideoLoaded.run();
            }

            // Produce thread sync problems
            // Attempt to read from field 'java.util.TreeMap$Node java.util.TreeMap$Node.left' on a null object reference
            //mTrackSelectorManager.fixTracksSelection();
        }
    }

    @Override
    public void onPlayerError(ExoPlaybackException error) {
        Log.e(TAG, "onPlayerError: " + error);

        // NOTE: Player is released at this point. So, there is no sense to restore the playback here.

        Throwable nested = error.getCause() != null ? error.getCause() : error;

        mEventListener.onEngineError(error.type, error.rendererIndex, nested);
    }

    @Override
    public void onPlayerStateChanged(boolean playWhenReady, int playbackState) {
        if (BuildConfig.DEBUG) {
            Log.d(TAG, "onPlayerStateChanged: " + TrackSelectorUtil.stateToString(playbackState));
        }

        PlayerCommands.onState(playbackState, getPositionMs());

        boolean isPlayPressed = Player.STATE_READY == playbackState && playWhenReady;
        boolean isPausePressed = Player.STATE_READY == playbackState && !playWhenReady;
        boolean isPlaybackEnded = Player.STATE_ENDED == playbackState && playWhenReady;
        boolean isBuffering = Player.STATE_BUFFERING == playbackState && playWhenReady;

        // Fix chapters (seek and play) after playback ends
        if (isPlaybackEnded && mIsEnded) {
            return;
        }

        if (playWhenReady) {
            mFrameStepper.onPlay();
        }

        if (isPlayPressed) {
            VideoStarts.onPlaying(mHasSurface);
            onHealthPlaying();
            mEventListener.onPlay();
        } else if (isPausePressed) {
            mHealth.onInterrupted(PlaybackHealth.RESUMED_BY_PAUSE);
            mEventListener.onPause();
        } else if (isPlaybackEnded) {
            mEventListener.onPlayEnd();
            mIsEnded = true;
        } else if (isBuffering) {
            mHealth.onInterrupted(PlaybackHealth.RESUMED_BY_BUFFERING);
            mEventListener.onBuffering();
        }

        if (getPositionMs() < getDurationMs()) {
            mIsEnded = false;
        }
    }

    @Override
    public void onPositionDiscontinuity(int reason) {
        Log.e(TAG, "onPositionDiscontinuity");

        if (reason == Player.DISCONTINUITY_REASON_SEEK) {
            mFrameStepper.onSeek();
            // Any seek (SponsorBlock, chapters, remote, not only the UI's): its buffering comes before onSeekProcessed and isn't a stall
            FormatAttempts.onSeek();
            mHealth.onInterrupted(PlaybackHealth.RESUMED_BY_SEEK);
        }

        mRangeMuter.onSeek();

        // Fix video loop on 480p with legacy codes enabled
        if (reason == Player.DISCONTINUITY_REASON_PERIOD_TRANSITION) {
            mPlayer.stop();
            mEventListener.onPlayEnd();
        }
    }

    @Override
    public void onSeekProcessed() {
        mEventListener.onSeekEnd();
    }

    public float getSpeed() {
        if (mPlayer != null) {
            return mPlayer.getPlaybackParameters().speed;
        } else {
            return -1;
        }
    }

    public void setSpeed(float speed) {
        if (mPlayer != null && speed > 0) {
            if (PlayerTweaksData.instance(mContext).isAudioTimeStretchingEnabled()) {
                mPlayer.setPlaybackParameters(new PlaybackParameters(speed, mPlayer.getPlaybackParameters().pitch));
            } else {
                mPlayer.setPlaybackParameters(new PlaybackParameters(speed, speed));
            }

            mTrackFormatter.setSpeed(speed);
            setQualityInfo(mTrackFormatter.getQualityLabel());
            mEventListener.onSpeedChanged(speed);
        }
    }

    public float getPitch() {
        if (mPlayer != null) {
            return mPlayer.getPlaybackParameters().pitch;
        } else {
            return -1;
        }
    }

    public void setPitch(float pitch) {
        if (mPlayer != null && pitch > 0) {
            mPlayer.setPlaybackParameters(new PlaybackParameters(mPlayer.getPlaybackParameters().speed, pitch));
        }
    }

    public void setVolume(float volume) {
        if (mPlayer != null && volume >= 0) {
            mVolume = Math.min(volume, 1f);
            mPlayer.setVolume(mIsMuted ? 0 : mVolume);

            //applyVolumeBoost(volume);
        }
    }
    
    public float getVolume() {
        if (mPlayer != null) {
            return mIsMuted ? mVolume : mPlayer.getVolume();
        } else {
            return 1;
        }
    }

    /**
     * Mutes the sound during the ranges of the video that's open (see CensoredWords). Opening another video drops them.
     */
    public void setMuteRanges(@Nullable List<Range> ranges) {
        mRangeMuter.setRanges(ranges);
    }

    private void onMuteChanged(boolean muted) {
        if (mPlayer == null) {
            mIsMuted = false;
            return;
        }

        if (muted && !mIsMuted) {
            mVolume = mPlayer.getVolume();
        }

        mIsMuted = muted;
        mPlayer.setVolume(muted ? 0 : mVolume);
    }

    /**
     * Fixes video artifacts when switching to the next video.<br/>
     * Also could help with memory leaks(??)<br/>
     * Without this also you'll have problems with track quality switching(??).
     */
    public void resetPlayerState() {
        if (containsMedia()) {
            mPlayer.stop(true);
        }
    }
    
    public void setOnVideoLoaded(Runnable onVideoLoaded) {
        mOnVideoLoaded = onVideoLoaded;
    }

    private void onFramePositionChanged(long positionMs) {
        if (mPlayerView != null) {
            mPlayerView.setFramePositionMs(positionMs);
        }
    }

    private void setQualityInfo(String qualityInfoStr) {
        if (mPlayerView != null && qualityInfoStr != null) {
            mPlayerView.setQualityInfo(qualityInfoStr);
        }
    }

    private void applyVolumeBoost(float volume) {
        if (mPlayer == null) {
            return;
        }

        if (mVolumeBooster != null) {
            mPlayer.removeAudioListener(mVolumeBooster);
            mVolumeBooster = null;
        }

        // 5.1 audio cannot be boosted (format isn't supported error)
        // also, other 2.0 tracks in 5.1 group is already too loud. so cancel them too.
        if (volume > 1f && !contains51Audio() && Build.VERSION.SDK_INT >= 19) {
            mVolumeBooster = new VolumeBooster(true, volume, null);
            mPlayer.addAudioListener(mVolumeBooster);
        }
    }
    
    private boolean contains51Audio() {
        if (mTrackSelectorManager == null || mTrackSelectorManager.getAudioTracks() == null) {
            return false;
        }

        for (MediaTrack track : mTrackSelectorManager.getAudioTracks()) {
            if (TrackSelectorUtil.is51Audio(track.format)) {
                return true;
            }
        }

        return false;
    }

    private void releasePlayer() {
        Utils.removeCallbacks(mHealthCheck);
        // Left before its start played: what it played of it
        onStartFrames(mHealth.endStart());
        LastState.onPlayer(mContext, false, false);
        mFrameStepper.setPlayer(null, null);
        mVideoRenderer = null;
        mRangeMuter.setPlayer(null);

        if (mPlayer == null) {
            return;
        }

        try {
            mPlayer.removeListener(this);
            mPlayer.removeAnalyticsListener(mDiagnosticsListener);
            mPlayer.stop(true); // Cause input lags due to high cpu load?
            mPlayer.clearVideoSurface();
            mPlayer.release();
        } catch (ArrayIndexOutOfBoundsException e) { // thrown on stop()
            e.printStackTrace();
        } finally {
            mPlayer = null;
        }
    }
}
