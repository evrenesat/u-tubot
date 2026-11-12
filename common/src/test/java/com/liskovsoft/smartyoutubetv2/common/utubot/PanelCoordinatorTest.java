package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Before;
import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

public class PanelCoordinatorTest {
    private static final long DELAY_MS = 1800;
    private final FakeScheduler mScheduler = new FakeScheduler();
    private final List<String> mEvents = new ArrayList<>();
    private PanelCoordinator mCoordinator;

    @Before
    public void setUp() {
        mCoordinator = new PanelCoordinator(mScheduler, () -> DELAY_MS, new PanelCoordinator.Output() {
            @Override
            public void showWaiting(String key) {
                mEvents.add("waiting:" + key);
            }

            @Override
            public void showSettled(String key) {
                mEvents.add("settled:" + key);
            }

            @Override
            public void hide() {
                mEvents.add("hide");
            }
        });
        mCoordinator.setEnabled(true);
        mCoordinator.onResume();
    }

    @Test
    public void aFocusedCardShowsTheTitleAtOnceAndSettlesAfterThePause() {
        mCoordinator.onCardFocused("a");

        assertEquals(Arrays.asList("waiting:a"), mEvents);
        assertTrue(mCoordinator.isVisible());

        mScheduler.advance(DELAY_MS);
        assertEquals(Arrays.asList("waiting:a", "settled:a"), mEvents);
    }

    @Test
    public void movingOnReplacesTheWaitingCardAndNeverSettlesTheOneLeft() {
        mCoordinator.onCardFocused("a");
        mScheduler.advance(1000);
        mCoordinator.onCardFocused("b");
        mScheduler.advance(1000);

        assertEquals(Arrays.asList("waiting:a", "waiting:b"), mEvents);

        mScheduler.advance(DELAY_MS);
        assertEquals(Arrays.asList("waiting:a", "waiting:b", "settled:b"), mEvents);
    }

    @Test
    public void focusOnTheSidebarHidesThePanelAndDropsTheRequest() {
        mCoordinator.onCardFocused("a");
        mScheduler.advance(DELAY_MS);

        mCoordinator.onNothingFocused();
        mScheduler.advance(DELAY_MS * 3);

        assertEquals(Arrays.asList("waiting:a", "settled:a", "hide"), mEvents);
        assertFalse(mCoordinator.isVisible());
        assertNull(mCoordinator.getCurrentKey());
    }

    @Test
    public void anEmptyOrLoadingListHasNoCardAndNoPanel() {
        mCoordinator.onNothingFocused();
        mCoordinator.onCardFocused(null);
        mScheduler.advance(DELAY_MS * 3);

        assertTrue(mEvents.isEmpty());
        assertFalse(mCoordinator.isVisible());
    }

    @Test
    public void aSectionChangeBeforeThePauseEndsDropsTheWaitingCard() {
        mCoordinator.onCardFocused("a");
        mScheduler.advance(1000);
        mCoordinator.onNothingFocused();
        mScheduler.advance(DELAY_MS * 3);

        assertEquals(Arrays.asList("waiting:a", "hide"), mEvents);
    }

    @Test
    public void aCardThatLeavesTheScreenHidesThePanel() {
        mCoordinator.onCardFocused("a");
        mCoordinator.onCardGone("other");
        assertTrue(mCoordinator.isVisible());

        mCoordinator.onCardGone("a");
        mScheduler.advance(DELAY_MS * 3);

        assertEquals(Arrays.asList("waiting:a", "hide"), mEvents);
    }

    @Test
    public void pausingTheScreenHidesThePanel() {
        mCoordinator.onCardFocused("a");
        mCoordinator.onPause();
        mScheduler.advance(DELAY_MS * 3);

        assertEquals(Arrays.asList("waiting:a", "hide"), mEvents);

        mCoordinator.onCardFocused("b");
        assertEquals(2, mEvents.size());
    }

    @Test
    public void resumingWithoutACardShowsNothingAndWithOneWaitsAgain() {
        mCoordinator.onPause();
        mCoordinator.onResume();
        assertTrue(mEvents.isEmpty());

        mCoordinator.onCardFocused("a");
        assertEquals(Arrays.asList("waiting:a"), mEvents);
    }

    @Test
    public void theModeOffHidesThePanelAndIgnoresCards() {
        mCoordinator.onCardFocused("a");
        mCoordinator.setEnabled(false);
        mCoordinator.onCardFocused("b");
        mScheduler.advance(DELAY_MS * 3);

        assertEquals(Arrays.asList("waiting:a", "hide"), mEvents);
    }

    @Test
    public void theSummaryViewHidesThePanelAndKeepsItOut() {
        mCoordinator.onCardFocused("a");
        mCoordinator.setModalOpen(true);
        mCoordinator.onCardFocused("b");
        mCoordinator.onNothingFocused();
        mScheduler.advance(DELAY_MS * 3);

        assertEquals(Arrays.asList("waiting:a", "hide"), mEvents);

        mCoordinator.setModalOpen(false);
        mCoordinator.onCardFocused("a");
        assertEquals("waiting:a", mEvents.get(mEvents.size() - 1));
    }

    @Test
    public void aHeldKeyKeepsTheCardWaiting() {
        mCoordinator.onCardFocused("a");

        for (int i = 0; i < 100; i++) {
            mScheduler.advance(100);
            mCoordinator.onKeyActivity();
        }

        assertEquals(Arrays.asList("waiting:a"), mEvents);
    }

    @Test
    public void returningToTheSettledCardAfterTheSidebarWaitsAgain() {
        mCoordinator.onCardFocused("a");
        mScheduler.advance(DELAY_MS);
        mCoordinator.onNothingFocused();
        mCoordinator.onCardFocused("a");

        assertEquals(Arrays.asList("waiting:a", "settled:a", "hide", "waiting:a"), mEvents);
    }

    @Test
    public void dismissHidesThePanelAndTheNextCardBringsItBackAfterThePause() {
        mCoordinator.onCardFocused("a");
        mScheduler.advance(DELAY_MS);
        mEvents.clear();

        assertTrue(mCoordinator.dismiss());
        assertFalse(mCoordinator.isVisible());
        assertEquals(Arrays.asList("hide"), mEvents);

        mScheduler.advance(10 * DELAY_MS);
        assertEquals(Arrays.asList("hide"), mEvents);

        mCoordinator.onCardFocused("b");
        assertEquals(Arrays.asList("hide", "waiting:b"), mEvents);
        mScheduler.advance(DELAY_MS);
        assertEquals(Arrays.asList("hide", "waiting:b", "settled:b"), mEvents);
    }

    @Test
    public void dismissWhileWaitingCancelsTheRequestOfThatCard() {
        mCoordinator.onCardFocused("a");
        mScheduler.advance(DELAY_MS / 2);

        assertTrue(mCoordinator.dismiss());
        mScheduler.advance(DELAY_MS);

        assertEquals(Arrays.asList("waiting:a", "hide"), mEvents);
    }

    @Test
    public void dismissWithoutAPanelDoesNothing() {
        assertFalse(mCoordinator.dismiss());
        assertTrue(mEvents.isEmpty());
    }

    @Test
    public void dismissKeepsThePanelModeOn() {
        mCoordinator.onCardFocused("a");
        mCoordinator.dismiss();
        mCoordinator.onCardFocused("a");

        assertTrue(mCoordinator.isVisible());
    }
}
