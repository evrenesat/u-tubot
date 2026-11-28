package com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager;

import com.liskovsoft.mediaserviceinterfaces.data.MediaItemFormatInfo;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.CensoredWords.Range;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;

import java.io.InputStream;
import java.util.List;

public interface PlayerEngine extends PlayerConstants {
    void openSabr(MediaItemFormatInfo formatInfo);
    void openDash(MediaItemFormatInfo formatInfo);
    void openDash(InputStream dashManifest);
    void openDashUrl(String dashManifestUrl);
    void openHlsUrl(String hlsPlaylistUrl);
    void openUrlList(List<String> urlList);

    /** A single direct stream (a film's MKV or MP4) */
    void openProgressiveUrl(String url);

    /**
     * A film's subtitle from the internet, side-loaded next to the file's own tracks and selected; null takes it away
     *
     * @param file the WebVTT file, already shifted by the viewer's delay
     */
    void setFilmSubtitle(@androidx.annotation.Nullable java.io.File file, String id, String lang, String label);
    void openMerged(MediaItemFormatInfo formatInfo, String hlsPlaylistUrl);
    void openMerged(InputStream dashManifest, String hlsPlaylistUrl);
    long getPositionMs();
    void setPositionMs(long positionMs);
    long getDurationMs();
    /**
     * Up to where the media is loaded: a seek before it plays at once
     */
    long getBufferedPositionMs();
    void setPlayWhenReady(boolean play);
    boolean getPlayWhenReady();
    /**
     * Pauses (if playing) and shows the next frame
     */
    void nextFrame();
    boolean isPlaying();
    boolean isLoading();
    List<FormatItem> getVideoFormats();
    List<FormatItem> getAudioFormats();
    List<FormatItem> getSubtitleFormats();
    void setFormat(FormatItem option);
    FormatItem getVideoFormat();
    FormatItem getAudioFormat();
    FormatItem getSubtitleFormat();
    boolean isEngineInitialized();
    void restartEngine();
    void reloadPlayback();
    void blockEngine(boolean block);
    boolean isEngineBlocked();
    boolean isInPIPMode();
    boolean containsMedia();
    void setSpeed(float speed);
    float getSpeed();
    void setPitch(float pitch);
    float getPitch();
    void setVolume(float volume);
    float getVolume();
    /**
     * Mutes the sound during the ranges of the video that's open. Opening another video drops them.
     */
    void setMuteRanges(List<Range> ranges);
    void setResizeMode(int mode);
    int getResizeMode();
    void setZoomPercents(int percents);
    void setAspectRatio(float ratio);
    void setRotationAngle(int angle);
    void setVideoFlipEnabled(boolean enabled);
    void setVideoGravity(int gravity);
}
