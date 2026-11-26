package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;

/**
 * How a position in the video maps to the position inside an active director's cut and the kept part the playback is in (issue 141). The
 * cut keeps its parts and skips the rest, so the cut time is the kept parts before the position plus how far into the current part it is.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutTimeTest {
    @Test
    public void aPositionInsideAPart_isItsCutTimeAndPartNumber() {
        Cut cut = cut(300_000, parts(
                part("a", 0, 60_000),
                part("b", 100_000, 220_000),
                part("c", 300_000, 420_000)));

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 160_000);

        // 60 000 of part a, then 60 000 into part b: 120 000 in the cut, part 2 of 3
        assertEquals(120_000, position.cutPositionMs);
        assertEquals(2, position.partIndex);
        assertEquals(3, position.partCount);
        assertEquals(300_000, position.totalKeptMs);
    }

    @Test
    public void theFirstPartStartsAtCutTimeZero() {
        Cut cut = cut(120_000, parts(part("a", 0, 60_000), part("b", 100_000, 160_000)));

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 0);

        assertEquals(0, position.cutPositionMs);
        assertEquals(1, position.partIndex);
        assertEquals(2, position.partCount);
    }

    @Test
    public void aPositionInTheLastPart_isAtTheLastPartNumber() {
        Cut cut = cut(500_000, parts(part("a", 0, 60_000), part("b", 100_000, 220_000), part("c", 300_000, 420_000)));

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 410_000);

        // 60 000 + 120 000 of the first two parts, then 110 000 into the third
        assertEquals(290_000, position.cutPositionMs);
        assertEquals(3, position.partIndex);
        assertEquals(300_000, position.totalKeptMs);
    }

    @Test
    public void aPositionPastTheLastPartIsAtTheEndOfTheCut() {
        Cut cut = cut(500_000, parts(part("a", 0, 60_000), part("b", 100_000, 220_000)));

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 499_000);

        assertEquals(180_000, position.cutPositionMs); // 60 000 + 120 000, the whole kept length
        assertEquals(0, position.partIndex); // the playback is past the kept parts, in the drop to the end
        assertEquals(2, position.partCount);
        assertEquals(180_000, position.totalKeptMs);
    }

    @Test
    public void aPositionInADropReportsTheKeptLengthSoFarAndNoPart() {
        Cut cut = cut(400_000, parts(part("a", 0, 60_000), part("b", 200_000, 300_000)));

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 150_000);

        assertEquals(60_000, position.cutPositionMs); // only part a so far
        assertEquals(0, position.partIndex); // between the parts, in a dropped range
        assertEquals(2, position.partCount);
        assertEquals(160_000, position.totalKeptMs);
    }

    @Test
    public void aPositionBeforeTheFirstPartIsAtCutTimeZeroWithNoPart() {
        Cut cut = cut(400_000, parts(part("a", 100_000, 200_000), part("b", 300_000, 400_000)));

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 50_000);

        assertEquals(0, position.cutPositionMs);
        assertEquals(0, position.partIndex);
        assertEquals(2, position.partCount);
    }

    @Test
    public void aCutWithNoPartsMapsToZeroWithNoPart() {
        Cut cut = cut(240_000, List.of());

        UtubotCutTime.CutPosition position = UtubotCutTime.of(cut, 120_000);

        assertEquals(0, position.cutPositionMs);
        assertEquals(0, position.partIndex);
        assertEquals(0, position.partCount);
        assertEquals(0, position.totalKeptMs);
    }

    @Test
    public void aNullCutMapsToZero() {
        UtubotCutTime.CutPosition position = UtubotCutTime.of(null, 120_000);

        assertEquals(0, position.cutPositionMs);
        assertEquals(0, position.partCount);
    }

    private static Cut cut(long keptMs, List<CutPart> parts) {
        Cut cut = new Cut();
        cut.keptMs = keptMs;
        cut.parts = parts;
        return cut;
    }

    private static CutPart part(String label, long startMs, long endMs) {
        CutPart part = new CutPart();
        part.label = label;
        part.startMs = startMs;
        part.endMs = endMs;
        return part;
    }

    private static List<CutPart> parts(CutPart... parts) {
        return new ArrayList<>(Arrays.asList(parts));
    }
}
