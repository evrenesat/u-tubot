package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;

import org.junit.Test;

import java.util.Arrays;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotCutNavigatorTest {
    private final Cut mCut = cut();

    private Cut cut() {
        Cut cut = new Cut();
        cut.videoId = "abcdefghijk";
        cut.durationMs = 70_000;
        cut.parts = Arrays.asList(part(10_000, 20_000), part(30_000, 40_000), part(50_000, 60_000));
        cut.skipRangesMs = Arrays.asList(new long[]{0, 10_000}, new long[]{20_000, 30_000},
                new long[]{40_000, 50_000}, new long[]{60_000, 70_000});
        return cut;
    }

    private static CutPart part(long startMs, long endMs) {
        CutPart part = new CutPart();
        part.startMs = startMs;
        part.endMs = endMs;
        return part;
    }

    @Test
    public void nextFromTheStartOfAPart_isTheFollowingPart() {
        assertEquals(30_000, UtubotCutNavigator.nextPartStartMs(mCut, 10_000));
    }

    @Test
    public void nextFromTheMiddleOfAPart_isTheFollowingPart() {
        assertEquals(30_000, UtubotCutNavigator.nextPartStartMs(mCut, 15_000));
    }

    @Test
    public void nextFromACutOut_isThePartThatFollowsIt() {
        assertEquals(30_000, UtubotCutNavigator.nextPartStartMs(mCut, 25_000));
        assertEquals(10_000, UtubotCutNavigator.nextPartStartMs(mCut, 5_000));
    }

    @Test
    public void nextFromTheLastPart_hasNoNext() {
        assertEquals(UtubotCutNavigator.NONE, UtubotCutNavigator.nextPartStartMs(mCut, 55_000));
        assertEquals(UtubotCutNavigator.NONE, UtubotCutNavigator.nextPartStartMs(mCut, 65_000));
    }

    @Test
    public void previousFromTheStartOfTheFirstPart_hasNoPrevious() {
        assertEquals(UtubotCutNavigator.NONE, UtubotCutNavigator.previousPartStartMs(mCut, 10_000));
    }

    @Test
    public void previousFromTheMiddleOfAPart_isThePartBeforeIt() {
        assertEquals(UtubotCutNavigator.NONE, UtubotCutNavigator.previousPartStartMs(mCut, 15_000));
        assertEquals(10_000, UtubotCutNavigator.previousPartStartMs(mCut, 35_000));
    }

    @Test
    public void previousFromACutOut_isThePartBeforeIt() {
        assertEquals(10_000, UtubotCutNavigator.previousPartStartMs(mCut, 25_000));
        assertEquals(30_000, UtubotCutNavigator.previousPartStartMs(mCut, 45_000));
    }

    @Test
    public void previousFromTheLastPart_isThePartBeforeIt() {
        assertEquals(30_000, UtubotCutNavigator.previousPartStartMs(mCut, 50_000));
        assertEquals(50_000, UtubotCutNavigator.previousPartStartMs(mCut, 65_000));
    }

    @Test
    public void aCutOut_hasABadgeWithTheNextPartAndItsCountdown() {
        UtubotCutNavigator.Badge badge = UtubotCutNavigator.badgeAt(mCut, 25_000);

        assertTrue(badge.visible);
        assertTrue(badge.hasNext());
        assertEquals(30_000, badge.nextPartStartMs);
        assertEquals(5_000, badge.remainingMs);
    }

    @Test
    public void aKeptPart_hasNoBadge() {
        assertFalse(UtubotCutNavigator.badgeAt(mCut, 15_000).visible);
        assertFalse(UtubotCutNavigator.badgeAt(mCut, 30_000).visible); // the start of a kept part
    }

    @Test
    public void theStartOfACutOut_hasTheBadge() {
        UtubotCutNavigator.Badge badge = UtubotCutNavigator.badgeAt(mCut, 20_000);

        assertTrue(badge.visible);
        assertEquals(10_000, badge.remainingMs);
    }

    @Test
    public void aTrailingCutOut_hasTheBadgeWithoutANextPart() {
        UtubotCutNavigator.Badge badge = UtubotCutNavigator.badgeAt(mCut, 65_000);

        assertTrue(badge.visible);
        assertFalse(badge.hasNext());
        assertEquals(UtubotCutNavigator.NONE, badge.nextPartStartMs);
    }

    @Test
    public void withoutACut_thereIsNoBadgeAndNoPart() {
        assertFalse(UtubotCutNavigator.badgeAt(null, 15_000).visible);
        assertEquals(UtubotCutNavigator.NONE, UtubotCutNavigator.nextPartStartMs(null, 15_000));
        assertEquals(UtubotCutNavigator.NONE, UtubotCutNavigator.previousPartStartMs(null, 15_000));
    }

    @Test
    public void partsNeedNotBeInOrderForTheNextAndPreviousMath() {
        Cut cut = cut();
        cut.parts = Arrays.asList(part(50_000, 60_000), part(10_000, 20_000), part(30_000, 40_000));

        assertEquals(30_000, UtubotCutNavigator.nextPartStartMs(cut, 15_000));
        assertEquals(10_000, UtubotCutNavigator.previousPartStartMs(cut, 35_000));
    }
}
