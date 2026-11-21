package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotCutSkipperTest {
    private static final long SKIP_1_START = 60_000;
    private static final long SKIP_1_END = 108_000;
    private static final long SKIP_2_START = 168_000;
    private static final long SKIP_2_END = 204_000;

    private final List<SponsorSegment> mSponsorSegments = new ArrayList<>();
    private final List<String> mSkippedCategories = new ArrayList<>();
    private UtubotCutSkipper mSkipper = skipper(cut());

    private Cut cut() {
        Cut cut = new Cut();
        cut.videoId = "abcdefghijk";
        cut.durationMs = 240_000;
        cut.keptMs = 156_000;
        cut.label = "No filler";
        cut.skipRangesMs = Arrays.asList(new long[]{SKIP_1_START, SKIP_1_END}, new long[]{SKIP_2_START, SKIP_2_END});
        return cut;
    }

    private UtubotCutSkipper skipper(Cut cut) {
        return new UtubotCutSkipper(cut, mSponsorSegments, category -> mSkippedCategories.contains(category));
    }

    private static SponsorSegment sponsor(long startMs, long endMs, String category) {
        return new SponsorSegment() {
            @Override
            public long getStartMs() {
                return startMs;
            }

            @Override
            public long getEndMs() {
                return endMs;
            }

            @Override
            public String getCategory() {
                return category;
            }

            @Override
            public String getAction() {
                return "skip";
            }
        };
    }

    @Test
    public void thePlaybackCrossingIntoADrop_isSkippedToItsEnd() {
        mSkipper.onPosition(59_000, 1f);

        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_400, 1f);

        assertTrue(decision.isJump());
        assertEquals(SKIP_1_END, decision.jumpToMs);
    }

    @Test
    public void thePlaybackJustBeforeADrop_isNotSkippedYet() {
        mSkipper.onPosition(58_000, 1f);

        assertFalse(mSkipper.onPosition(59_500, 1f).isJump());
    }

    @Test
    public void aSeekIntoTheMiddleOfADrop_winsAndPlays() {
        mSkipper.onPosition(20_000, 1f);

        // a seek: far more than a tick of the playback can move
        assertFalse(mSkipper.onPosition(90_000, 1f).isJump());
        // and the drop plays out: the position is inside it, never entered at its start
        assertFalse(mSkipper.onPosition(91_000, 1f).isJump());
        assertFalse(mSkipper.onPosition(107_500, 1f).isJump());
    }

    @Test
    public void aSeekExactlyToADropStart_winsAndPlays() {
        mSkipper.onPosition(20_000, 1f);

        assertFalse(mSkipper.onPosition(SKIP_1_START, 1f).isJump());
        assertFalse(mSkipper.onPosition(SKIP_1_START + 500, 1f).isJump());
    }

    @Test
    public void aSeekToJustBeforeADrop_thenPlayingThrough_skips() {
        mSkipper.onPosition(20_000, 1f);
        assertFalse(mSkipper.onPosition(58_000, 1f).isJump()); // the seek lands

        assertTrue(mSkipper.onPosition(60_100, 1f).isJump());
    }

    @Test
    public void aBackwardsMove_playsWhereItLanded() {
        mSkipper.onPosition(120_000, 1f);

        assertFalse(mSkipper.onPosition(90_000, 1f).isJump());
    }

    @Test
    public void theSecondDrop_isSkippedOnItsOwnCrossing() {
        mSkipper.onPosition(110_000, 1f);
        assertFalse(mSkipper.onPosition(167_000, 1f).isJump());

        UtubotCutSkipper.Decision decision = mSkipper.onPosition(168_300, 1f);
        assertTrue(decision.isJump());
        assertEquals(SKIP_2_END, decision.jumpToMs);
    }

    @Test
    public void aFasterPlayback_stillCrossesIntoTheWindow() {
        mSkipper.onPosition(56_000, 4f);

        // a tick of a 4x playback moves about 4 s of video; the window is wider accordingly
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_000, 4f);

        assertTrue(decision.isJump());
        assertEquals(SKIP_1_END, decision.jumpToMs);
    }

    @Test
    public void theJumpOfTheSkipper_isNotTakenForASeek() {
        mSkipper.onPosition(59_000, 1f);
        assertTrue(mSkipper.onPosition(60_400, 1f).isJump()); // jumps to 108000 and remembers the destination

        // at the destination: a kept part, no drop crossed, and no seek flagged either
        assertFalse(mSkipper.onPosition(109_000, 1f).isJump());
        // skipping still works afterwards: the next drop is crossed by the playback itself
        assertFalse(mSkipper.onPosition(167_000, 1f).isJump());
        assertTrue(mSkipper.onPosition(168_300, 1f).isJump());
    }

    @Test
    public void aSponsorSegmentStraddlingTheDestination_givesOneJump() {
        mSponsorSegments.add(sponsor(100_000, 130_000, "sponsor"));
        mSkippedCategories.add("sponsor");
        mSkipper = skipper(cut());

        mSkipper.onPosition(59_000, 1f);
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_400, 1f);

        assertTrue(decision.isJump());
        assertEquals(130_000, decision.jumpToMs);
    }

    @Test
    public void aSponsorSegmentRightAfterTheDestination_isPartOfTheSameJump() {
        mSponsorSegments.add(sponsor(110_000, 130_000, "sponsor"));
        mSkippedCategories.add("sponsor");
        mSkipper = skipper(cut());

        mSkipper.onPosition(59_000, 1f);
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_400, 1f);

        assertEquals(130_000, decision.jumpToMs);
    }

    @Test
    public void aSponsorSegmentFarAfterTheDestination_isNotSwallowed() {
        mSponsorSegments.add(sponsor(130_000, 150_000, "sponsor"));
        mSkippedCategories.add("sponsor");
        mSkipper = skipper(cut());

        mSkipper.onPosition(59_000, 1f);
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_400, 1f);

        assertEquals(SKIP_1_END, decision.jumpToMs);
    }

    @Test
    public void aSponsorSegmentNotSetToSkip_isNotSwallowed() {
        mSponsorSegments.add(sponsor(100_000, 130_000, "sponsor"));
        // the category is not in the skipped list: the sponsor block shows a dialog for it instead
        mSkipper = skipper(cut());

        mSkipper.onPosition(59_000, 1f);
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_400, 1f);

        assertEquals(SKIP_1_END, decision.jumpToMs);
    }

    @Test
    public void chainedSponsorSegments_areOneJump() {
        mSponsorSegments.add(sponsor(109_000, 120_000, "sponsor"));
        mSponsorSegments.add(sponsor(121_000, 130_000, "intro"));
        mSkippedCategories.add("sponsor");
        mSkippedCategories.add("intro");
        mSkipper = skipper(cut());

        mSkipper.onPosition(59_000, 1f);
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(60_400, 1f);

        assertEquals(130_000, decision.jumpToMs);
    }

    @Test
    public void aCutOfAnotherLength_isNotApplied() {
        Cut cut = cut();
        cut.durationMs = 300_000;

        assertFalse(UtubotCutSkipper.matchesDuration(cut, 240_000));
    }

    @Test
    public void aCutOfTheSameLengthWithinTwoSeconds_isApplied() {
        Cut cut = cut();
        cut.durationMs = 241_500;

        assertTrue(UtubotCutSkipper.matchesDuration(cut, 240_000));
    }

    @Test
    public void aCutWithoutAKnownLength_isNotApplied() {
        Cut cut = cut();
        cut.durationMs = 0;

        assertFalse(UtubotCutSkipper.matchesDuration(cut, 240_000));
    }

    @Test
    public void aCutWithNoSkips_neverJumps() {
        Cut cut = cut();
        cut.skipRangesMs = Collections.emptyList();
        mSkipper = skipper(cut);

        mSkipper.onPosition(0, 1f);

        for (int second = 1; second <= 240; second++) {
            assertFalse(mSkipper.onPosition(second * 1_000, 1f).isJump());
        }
    }

    @Test
    public void applyingInsideADrop_jumpsToItsEnd() {
        mSkipper.onPosition(20_000, 1f); // the cut is picked up while the playback sits in the drop

        UtubotCutSkipper.Decision decision = mSkipper.onAppliedAt(90_000);

        assertTrue(decision.isJump());
        assertEquals(SKIP_1_END, decision.jumpToMs);
    }

    @Test
    public void applyingInsideAnIntroDropAtTheStart_jumpsPastIt() {
        Cut cut = cut();
        cut.skipRangesMs = Collections.singletonList(new long[]{0, 90_000});
        UtubotCutSkipper intro = skipper(cut);

        UtubotCutSkipper.Decision decision = intro.onAppliedAt(5_000);

        assertTrue(decision.isJump());
        assertEquals(90_000, decision.jumpToMs);
    }

    @Test
    public void applyingOutsideEveryDrop_playsOn() {
        assertFalse(mSkipper.onAppliedAt(120_000).isJump());
    }

    @Test
    public void applyingExactlyAtADropEnd_playsOn() {
        assertFalse(mSkipper.onAppliedAt(SKIP_1_END).isJump());
    }

    @Test
    public void afterTheApplyJump_thePlaybackGoesOn() {
        assertTrue(mSkipper.onAppliedAt(90_000).isJump()); // jumps to SKIP_1_END and remembers the destination

        // at the destination: no drop crossed, and no seek flagged either
        assertFalse(mSkipper.onPosition(SKIP_1_END, 1f).isJump());
        // skipping still works afterwards: the next drop is crossed by the playback itself
        assertFalse(mSkipper.onPosition(167_000, 1f).isJump());
        assertTrue(mSkipper.onPosition(168_300, 1f).isJump());
    }

    @Test
    public void theApplyJump_swallowsASponsorSegmentAtTheDestination() {
        mSponsorSegments.add(sponsor(109_000, 130_000, "sponsor"));
        mSkippedCategories.add("sponsor");
        mSkipper = skipper(cut());

        UtubotCutSkipper.Decision decision = mSkipper.onAppliedAt(90_000);

        assertEquals(130_000, decision.jumpToMs);
    }
}