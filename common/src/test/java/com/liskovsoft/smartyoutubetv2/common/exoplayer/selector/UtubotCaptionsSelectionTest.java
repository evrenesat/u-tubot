package com.liskovsoft.smartyoutubetv2.common.exoplayer.selector;

import android.util.Pair;

import com.google.android.exoplayer2.Format;
import com.google.android.exoplayer2.source.TrackGroup;
import com.google.android.exoplayer2.source.TrackGroupArray;
import com.google.android.exoplayer2.trackselection.DefaultTrackSelector;
import com.google.android.exoplayer2.trackselection.TrackSelection.Definition;
import com.google.android.exoplayer2.util.MimeTypes;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.track.MediaTrack;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;

/**
 * The HQ captions track of u·tubot next to the subtitles of YouTube: picked by its id, not by the language it shares with them.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCaptionsSelectionTest {
    private static final Format YOUTUBE_TR = text("tr-TR", "tr");
    private static final Format YOUTUBE_EN = text("en", "en");
    private static final Format HQ_TR = text("utubot:Lqig_Ui9Hh0:tr", "tr");
    private static final Format HQ_OTHER_VIDEO_TR = text("utubot:jNQXAC9IVRw:tr", "tr");

    private TrackSelectorManager mManager;

    @Before
    public void setUp() {
        mManager = new TrackSelectorManager(RuntimeEnvironment.getApplication());
    }

    @Test
    public void hqTrack_isPickedWhenYouTubeOffersTheSameLanguage() {
        assertSame(HQ_TR, select(subtitle(HQ_TR), YOUTUBE_TR, HQ_TR));
    }

    @Test
    public void hqTrack_isPickedWhenItComesBeforeTheOthers() {
        assertSame(HQ_TR, select(subtitle(HQ_TR), HQ_TR, YOUTUBE_TR, YOUTUBE_EN));
    }

    @Test
    public void youTubeTrack_isStillPickedByLanguage() {
        assertSame(YOUTUBE_TR, select(subtitle(text("tr-TR", "tr")), YOUTUBE_TR, HQ_TR));
    }

    @Test
    public void hqTrackOfAnotherVideo_fallsBackToTheLanguage() {
        assertSame(YOUTUBE_TR, select(subtitle(HQ_OTHER_VIDEO_TR), YOUTUBE_TR, HQ_TR));
    }

    @Test
    public void hqTrackOfAnotherVideo_isNotPickedWhenNothingMatches() {
        mManager.selectTrack(subtitle(HQ_OTHER_VIDEO_TR));

        Pair<Definition, MediaTrack> selection = mManager.onSelectSubtitleTrack(groups(YOUTUBE_EN), DefaultTrackSelector.Parameters.DEFAULT);

        assertNull(selection);
    }

    @Test
    public void noSubtitles_afterTheHqTrack_selectsNothing() {
        mManager.setTrackSelector(new DefaultTrackSelector());
        select(subtitle(HQ_TR), YOUTUBE_TR, HQ_TR);

        mManager.selectTrack(MediaTrack.forRendererIndex(TrackSelectorManager.RENDERER_INDEX_SUBTITLE));

        assertNull(mManager.onSelectSubtitleTrack(groups(YOUTUBE_TR, HQ_TR), DefaultTrackSelector.Parameters.DEFAULT));
    }

    @Test
    public void hqTrack_isOfferedWithTheTracksOfYouTube() {
        mManager.selectTrack(subtitle(HQ_TR));
        mManager.onSelectSubtitleTrack(groups(YOUTUBE_TR, HQ_TR), DefaultTrackSelector.Parameters.DEFAULT);

        assertEquals(3, mManager.getSubtitleTracks().size()); // none + both
    }

    private Format select(MediaTrack origin, Format... formats) {
        mManager.selectTrack(origin);

        Pair<Definition, MediaTrack> selection = mManager.onSelectSubtitleTrack(groups(formats), DefaultTrackSelector.Parameters.DEFAULT);

        assertNotNull(selection);
        return selection.second.format;
    }

    private static TrackGroupArray groups(Format... formats) {
        TrackGroup[] groups = new TrackGroup[formats.length];

        for (int i = 0; i < formats.length; i++) {
            groups[i] = new TrackGroup(formats[i]);
        }

        return new TrackGroupArray(groups);
    }

    private static MediaTrack subtitle(Format format) {
        MediaTrack track = MediaTrack.forRendererIndex(TrackSelectorManager.RENDERER_INDEX_SUBTITLE);
        track.format = format;
        return track;
    }

    private static Format text(String id, String language) {
        return Format.createTextSampleFormat(id, MimeTypes.TEXT_VTT, 0, language);
    }
}
