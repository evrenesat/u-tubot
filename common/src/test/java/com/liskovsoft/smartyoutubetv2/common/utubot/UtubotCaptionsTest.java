package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.google.android.exoplayer2.Format;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotCaptionsTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";

    @Test
    public void trackId_carriesTheVideoAndTheLanguage() {
        CaptionTrack track = new CaptionTrack();
        track.lang = "tr";

        assertEquals("utubot:Lqig_Ui9Hh0:tr", UtubotCaptions.trackId(VIDEO, track));
    }

    @Test
    public void captionTrack_isRecognizedByItsId() {
        assertTrue(UtubotCaptions.isCaptionTrack(Format.createTextSampleFormat("utubot:Lqig_Ui9Hh0:tr", "text/vtt", 0, "tr")));
        assertFalse(UtubotCaptions.isCaptionTrack(Format.createTextSampleFormat("tr", "text/vtt", 0, "tr")));
        assertFalse(UtubotCaptions.isCaptionTrack(Format.createTextSampleFormat(null, "text/vtt", 0, "tr")));
        assertFalse(UtubotCaptions.isCaptionTrack(null));
    }

    @Test
    public void captionTrackOf_isTheTrackOfThatVideoOnly() {
        assertTrue(UtubotCaptions.isCaptionTrackOf("utubot:Lqig_Ui9Hh0:tr", VIDEO));
        assertFalse(UtubotCaptions.isCaptionTrackOf("utubot:jNQXAC9IVRw:tr", VIDEO));
        assertFalse(UtubotCaptions.isCaptionTrackOf("tr", VIDEO));
        assertFalse(UtubotCaptions.isCaptionTrackOf(null, VIDEO));
        assertFalse(UtubotCaptions.isCaptionTrackOf("utubot:Lqig_Ui9Hh0:tr", null));
    }

    @Test
    public void savedChoice_doesNotReplaceTheHqTrackOfTheVideo() {
        assertFalse(UtubotCaptions.mayRestoreSavedChoice("utubot:Lqig_Ui9Hh0:tr", VIDEO));
    }

    @Test
    public void savedChoice_replacesTheHqTrackOfAnotherVideo() {
        assertTrue(UtubotCaptions.mayRestoreSavedChoice("utubot:jNQXAC9IVRw:tr", VIDEO));
    }

    @Test
    public void savedChoice_replacesAnyOtherTrackOrNone() {
        assertTrue(UtubotCaptions.mayRestoreSavedChoice("en", VIDEO));
        assertTrue(UtubotCaptions.mayRestoreSavedChoice(null, VIDEO));
        assertTrue(UtubotCaptions.mayRestoreSavedChoice("utubot:Lqig_Ui9Hh0:tr", null));
    }

    @Test
    public void sameSource_tellsTheHqTrackFromOneOfYouTube() {
        assertTrue(UtubotCaptions.isSameSource("utubot:Lqig_Ui9Hh0:tr", "utubot:Lqig_Ui9Hh0:en"));
        assertTrue(UtubotCaptions.isSameSource("tr", "en"));
        assertTrue(UtubotCaptions.isSameSource(null, "en"));
        assertFalse(UtubotCaptions.isSameSource("utubot:Lqig_Ui9Hh0:tr", "tr"));
        assertFalse(UtubotCaptions.isSameSource(null, "utubot:Lqig_Ui9Hh0:tr"));
    }

    @Test
    public void atTheStart_theSettingDecides() {
        assertTrue(UtubotCaptions.shouldSelect(true, false));
        assertFalse(UtubotCaptions.shouldSelect(false, false));
    }

    @Test
    public void captionsTheUserAskedFor_areSelectedWhateverTheSettingSays() {
        assertTrue(UtubotCaptions.shouldSelect(true, true));
        assertTrue(UtubotCaptions.shouldSelect(false, true));
    }
}
