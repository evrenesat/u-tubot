package com.liskovsoft.smartyoutubetv2.common.utubot;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmPlaybackSettings.Option;

import org.junit.Test;

public class UtubotFilmPlaybackSettingsTest {
    @Test
    public void aYouTubeVideoKeepsEveryOption() {
        for (Option option : Option.values()) {
            assertTrue(option.name(), UtubotFilmPlaybackSettings.isShown(option, false));
        }
    }

    @Test
    public void aFilmHidesWhatIsTiedToYouTubeFormats() {
        assertFalse(UtubotFilmPlaybackSettings.isShown(Option.VIDEO_FORMATS, true));
        assertFalse(UtubotFilmPlaybackSettings.isShown(Option.VIDEO_PRESETS, true));
        assertFalse(UtubotFilmPlaybackSettings.isShown(Option.NETWORK_ENGINE, true));
        assertFalse(UtubotFilmPlaybackSettings.isShown(Option.AUDIO_LANGUAGE_LIST, true));
    }

    @Test
    public void aFilmKeepsWhatWorksOnAnyStream() {
        assertTrue(UtubotFilmPlaybackSettings.isShown(Option.AUDIO_TRACKS, true));
        assertTrue(UtubotFilmPlaybackSettings.isShown(Option.AUDIO_DELAY, true));
        assertTrue(UtubotFilmPlaybackSettings.isShown(Option.VIDEO_BUFFER, true));
        assertTrue(UtubotFilmPlaybackSettings.isShown(Option.PITCH_EFFECT, true));
        assertTrue(UtubotFilmPlaybackSettings.isShown(Option.VIDEO_ZOOM, true));
        assertTrue(UtubotFilmPlaybackSettings.isShown(Option.AUTO_FRAME_RATE, true));
    }
}
