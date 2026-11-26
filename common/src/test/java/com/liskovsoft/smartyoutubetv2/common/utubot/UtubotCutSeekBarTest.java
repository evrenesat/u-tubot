package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.graphics.Color;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerUI;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;

import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutSeekBarTest {
    private final List<List<SeekBarSegment>> mWritten = new ArrayList<>();
    private final PlayerUI mPlayer = recordingPlayer();

    @After
    public void tearDown() {
        UtubotCutSeekBar.setCut(null, null);
        UtubotCutSeekBar.setSponsor(mPlayer, null); // the sponsor segments are remembered between the writes now
    }

    /**
     * A player view that only remembers the seek bar segments it was given
     */
    private PlayerUI recordingPlayer() {
        return (PlayerUI) Proxy.newProxyInstance(PlayerUI.class.getClassLoader(), new Class<?>[]{PlayerUI.class},
                (proxy, method, args) -> {
                    if ("setSeekBarSegments".equals(method.getName())) {
                        @SuppressWarnings("unchecked")
                        List<SeekBarSegment> segments = (List<SeekBarSegment>) args[0];
                        mWritten.add(segments);
                        return null;
                    }

                    Class<?> type = method.getReturnType();

                    if (type == boolean.class) {
                        return false;
                    } else if (type == int.class) {
                        return 0;
                    } else if (type == long.class) {
                        return 0L;
                    } else if (type == float.class) {
                        return 0f;
                    }

                    return null;
                });
    }

    @Test
    public void withoutACut_theSponsorWritesPassThrough() {
        UtubotCutSeekBar.wipe(mPlayer, video("abc"));
        assertNull(mWritten.get(0));

        UtubotCutSeekBar.setSponsor(mPlayer, sponsorSegments());
        assertEquals(1, mWritten.get(1).size());
    }

    @Test
    public void theResetOfAnotherVideo_clearsEverything() {
        UtubotCutSeekBar.setCut("abc", cutSegments());
        mWritten.clear();

        UtubotCutSeekBar.wipe(mPlayer, video("xyz"));

        assertNull(mWritten.get(0));
    }

    @Test
    public void theResetOfTheCutVideo_keepsTheCut() {
        UtubotCutSeekBar.setCut("abc", cutSegments());
        mWritten.clear();

        UtubotCutSeekBar.wipe(mPlayer, video("abc"));

        assertEquals(2, mWritten.get(0).size());
    }

    @Test
    public void theSponsorSegments_areLaidNextToTheCutOnes() {
        UtubotCutSeekBar.setCut("abc", cutSegments());
        mWritten.clear();

        UtubotCutSeekBar.setSponsor(mPlayer, sponsorSegments());

        List<SeekBarSegment> both = mWritten.get(0);
        assertEquals(3, both.size());
        assertEquals(10, Math.round(both.get(0).startProgress * 100));
        assertEquals(70, Math.round(both.get(2).startProgress * 100));
    }

    @Test
    public void aClearedCut_leavesTheSponsorWritesAlone() {
        UtubotCutSeekBar.setCut("abc", cutSegments());
        UtubotCutSeekBar.setCut("abc", null);

        UtubotCutSeekBar.setSponsor(mPlayer, sponsorSegments());
        assertSame(sponsorSegments().size(), mWritten.get(0).size());
    }

    @Test
    public void aCutAppliedAfterTheSponsorWrite_isPaintedWithTheSponsorColours() {
        UtubotCutSeekBar.setSponsor(mPlayer, sponsorSegments());
        UtubotCutSeekBar.setCut("abc", cutSegments());
        mWritten.clear();

        UtubotCutSeekBar.paint(mPlayer);

        List<SeekBarSegment> both = mWritten.get(0);
        assertEquals(3, both.size());
        assertEquals(10, Math.round(both.get(0).startProgress * 100));
        assertEquals(70, Math.round(both.get(2).startProgress * 100));
    }

    @Test
    public void turningTheCutOff_leavesOnlyTheSponsorColours() {
        UtubotCutSeekBar.setSponsor(mPlayer, sponsorSegments());
        UtubotCutSeekBar.setCut("abc", cutSegments());
        UtubotCutSeekBar.setCut("abc", null);
        mWritten.clear();

        UtubotCutSeekBar.paint(mPlayer);

        List<SeekBarSegment> sponsorOnly = mWritten.get(0);
        assertEquals(1, sponsorOnly.size());
        assertEquals(Color.GREEN, sponsorOnly.get(0).color);
    }

    @Test
    public void theWipeOfAnotherVideo_forgetsTheSponsorColours() {
        UtubotCutSeekBar.setSponsor(mPlayer, sponsorSegments());
        UtubotCutSeekBar.wipe(mPlayer, video("xyz"));
        mWritten.clear();

        UtubotCutSeekBar.paint(mPlayer);

        assertNull(mWritten.get(0));
    }

    @Test
    public void theKeptPartsAreBrightAndTheCutOutsDarkAndHatched() {
        Cut cut = new Cut();
        cut.durationMs = 100_000;
        cut.parts = Arrays.asList(part(10_000, 40_000), part(60_000, 90_000));
        cut.skipRangesMs = Arrays.asList(new long[]{0, 10_000}, new long[]{40_000, 60_000}, new long[]{90_000, 100_000});

        List<SeekBarSegment> segments = UtubotCutSeekBar.segmentsFor(cut, 100_000);

        assertEquals(5, segments.size());
        // kept parts come first: bright and plain
        assertEquals(UtubotCutSeekBar.KEPT_COLOR, segments.get(0).color);
        assertFalse(segments.get(0).hatched);
        assertEquals(0.10f, segments.get(0).startProgress, 0.001f);
        assertEquals(0.40f, segments.get(0).endProgress, 0.001f);
        assertEquals(UtubotCutSeekBar.KEPT_COLOR, segments.get(1).color);
        // then the cut-outs: dark and hatched
        assertEquals(UtubotCutSeekBar.CUT_COLOR, segments.get(2).color);
        assertTrue(segments.get(2).hatched);
        assertEquals(0.40f, segments.get(3).startProgress, 0.001f);
        assertEquals(0.60f, segments.get(3).endProgress, 0.001f);
        assertTrue(segments.get(4).hatched);
    }

    @Test
    public void aCutWithoutPartsStillDrawsItsKeptRanges() {
        Cut cut = new Cut();
        cut.durationMs = 100_000;
        cut.skipRangesMs = Collections.singletonList(new long[]{20_000, 30_000});

        List<SeekBarSegment> segments = UtubotCutSeekBar.segmentsFor(cut, 100_000);

        assertEquals(3, segments.size()); // the two kept ranges and the cut-out between them
        assertEquals(UtubotCutSeekBar.KEPT_COLOR, segments.get(0).color);
        assertEquals(0f, segments.get(0).startProgress, 0.001f);
        assertEquals(0.20f, segments.get(0).endProgress, 0.001f);
        assertTrue(segments.get(2).hatched);
    }

    @Test
    public void anUnknownDurationDrawsNoSegments() {
        assertTrue(UtubotCutSeekBar.segmentsFor(new Cut(), 0).isEmpty());
        assertTrue(UtubotCutSeekBar.segmentsFor(null, 100_000).isEmpty());
    }

    private static CutPart part(long startMs, long endMs) {
        CutPart part = new CutPart();
        part.startMs = startMs;
        part.endMs = endMs;
        return part;
    }

    private Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        return video;
    }

    private List<SeekBarSegment> cutSegments() {
        SeekBarSegment first = new SeekBarSegment();
        first.startProgress = 0.10f;
        first.endProgress = 0.45f;
        SeekBarSegment second = new SeekBarSegment();
        second.startProgress = 0.55f;
        second.endProgress = 0.65f;
        return Arrays.asList(first, second);
    }

    private List<SeekBarSegment> sponsorSegments() {
        SeekBarSegment segment = new SeekBarSegment();
        segment.startProgress = 0.70f;
        segment.endProgress = 0.80f;
        segment.color = Color.GREEN;
        return new ArrayList<>(Collections.singletonList(segment));
    }
}