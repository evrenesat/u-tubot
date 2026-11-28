package com.liskovsoft.smartyoutubetv2.common.utubot;

/**
 * Which options of the player's "Playback settings" dialog apply to a film or an episode. A film is one progressive or MKV file the
 * player opens as it is, so what is tied to YouTube's formats (itags, codec preference, its network stack) is hidden over a film, and
 * what works on any stream stays.
 */
public final class UtubotFilmPlaybackSettings {
    /** The options of the dialog */
    public enum Option {
        /** The list of YouTube video formats (itags, VP9 and AV1) */
        VIDEO_FORMATS(false),
        /** The audio tracks of the stream: for a film, the file's own tracks */
        AUDIO_TRACKS(true),
        /** A global list of every language the device knows: a film offers only the languages its file has */
        AUDIO_LANGUAGE_LIST(false),
        /** Quality presets (4K, 1080p, ... mapped to YouTube formats) */
        VIDEO_PRESETS(false),
        /** Zoom, aspect and rotation */
        VIDEO_ZOOM(true),
        /** YouTube's network stack (Cronet, OkHttp, ...) */
        NETWORK_ENGINE(false),
        /** Buffer size and playback buffering */
        VIDEO_BUFFER(true),
        AUDIO_DELAY(true),
        /** Speed and pitch */
        PITCH_EFFECT(true),
        SLEEP_TIMER(true),
        /** Frame rate matching, added by the frame rate controller */
        AUTO_FRAME_RATE(true);

        public final boolean appliesToFilms;

        Option(boolean appliesToFilms) {
            this.appliesToFilms = appliesToFilms;
        }
    }

    private UtubotFilmPlaybackSettings() {
    }

    public static boolean isShown(Option option, boolean film) {
        return !film || option.appliesToFilms;
    }
}
