package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The slow self-scrolling of a text area: it crawls down a small amount every tick at the reading pace, stops at the bottom, pauses on a
 * key and resumes after the delay, and never moves when the content fits. The clock is the fake scheduler the test moves.
 */
public class UtubotAutoScrollTest {
    /** One tick of the crawl, the same tick the class uses. */
    private static final long TICK_MS = 40;
    /** Pause after a key, the class default. */
    private static final long RESUME_MS = 4000;
    private static final int SPEED_PX_PER_SEC = 100;

    private final FakeScheduler scheduler = new FakeScheduler();
    private final Target target = new Target();
    private UtubotAutoScroll autoScroll;

    private UtubotAutoScroll enabled() {
        target.max = 100;
        autoScroll = UtubotAutoScroll.of(scheduler, () -> SPEED_PX_PER_SEC, target);
        autoScroll.setEnabled(true);
        return autoScroll;
    }

    @Test
    public void itCrawlsDownOneStepEveryTickUntilTheBottom() {
        enabled();

        // No step before the first tick lands
        assertEquals(0, target.current);

        scheduler.advance(TICK_MS);
        assertEquals(4, target.current);

        scheduler.advance(TICK_MS);
        assertEquals(8, target.current);

        // 25 steps of 4 px reach the 100 px bottom and stop crawling
        scheduler.advance(TICK_MS * 23);
        assertEquals(100, target.current);
        assertEquals(0, scheduler.pending());
    }

    @Test
    public void aFasterSpeedTakesMorePixelsPerTick() {
        target.max = 100;
        autoScroll = UtubotAutoScroll.of(scheduler, () -> 250, target);
        autoScroll.setEnabled(true);

        scheduler.advance(TICK_MS);

        // ceil(250 * 40 / 1000) = 10 px in one tick
        assertEquals(10, target.current);
    }

    @Test
    public void thePaceMatchesTheLabelOverOneSecond() {
        target.max = 1000;
        autoScroll = UtubotAutoScroll.of(scheduler, () -> 45, target);
        autoScroll.setEnabled(true);

        // 25 ticks of 40 ms is one second; at 45 px/s it must move exactly 45 px, not the 50 the old whole-pixel ceil step gave.
        scheduler.advance(TICK_MS * 25);
        assertEquals(45, target.current);
    }

    @Test
    public void theThreePacesMoveDifferentAmountsInOneSecond() {
        int slow = distanceInOneSecond(30);
        int mid = distanceInOneSecond(45);
        int fast = distanceInOneSecond(60);

        // The three offered paces are three, each matching its label instead of collapsing to 50/50/75 px/s.
        assertTrue("30 px/s is slower than 45 px/s", slow < mid);
        assertTrue("45 px/s is slower than 60 px/s", mid < fast);
        assertEquals(30, slow);
        assertEquals(45, mid);
        assertEquals(60, fast);
    }

    private int distanceInOneSecond(long speedPxPerSec) {
        target.max = 1000;
        target.current = 0;
        UtubotAutoScroll pace = UtubotAutoScroll.of(scheduler, () -> speedPxPerSec, target);
        pace.setEnabled(true);
        scheduler.advance(TICK_MS * 25);
        pace.cancel();

        return target.current;
    }

    @Test
    public void itDoesNotCrawlWhenTheContentFits() {
        target.max = 0;
        autoScroll = UtubotAutoScroll.of(scheduler, () -> SPEED_PX_PER_SEC, target);
        autoScroll.setEnabled(true);

        scheduler.advance(TICK_MS * 10);

        assertEquals(0, target.current);
        assertEquals("nothing is scheduled when the content fits", 0, scheduler.pending());
    }

    @Test
    public void aKeyPausesTheCrawlAndItResumesAfterTheDelay() {
        enabled();

        scheduler.advance(TICK_MS);
        assertEquals(4, target.current);

        autoScroll.keyPressed();

        // The crawl is paused: a step that is still within the pause does not move it
        scheduler.advance(TICK_MS);
        assertEquals(4, target.current);

        // After the resume delay it continues from where the key left it
        scheduler.advance(RESUME_MS - TICK_MS);
        assertEquals(8, target.current);
    }

    @Test
    public void aKeyWhilePausedKeepsItPausedUntilTheNewDelayPasses() {
        enabled();

        scheduler.advance(TICK_MS);
        autoScroll.keyPressed();

        scheduler.advance(RESUME_MS / 2);
        autoScroll.keyPressed();

        scheduler.advance(RESUME_MS / 2);
        assertEquals("a second key restarts the delay, so it has not resumed yet", 4, target.current);

        scheduler.advance(RESUME_MS / 2);
        assertEquals(8, target.current);
    }

    @Test
    public void manualScrollBeforeTheResumeIsWhereTheCrawlContinues() {
        enabled();

        scheduler.advance(TICK_MS);
        autoScroll.keyPressed();

        // The user pages the text by hand while the crawl is paused
        target.current = 40;

        scheduler.advance(RESUME_MS);

        // The crawl resumes from the manual position, not from where it was before the key
        assertEquals(44, target.current);
    }

    @Test
    public void turningItOffStopsTheCrawl() {
        enabled();

        scheduler.advance(TICK_MS);
        assertEquals(4, target.current);

        autoScroll.setEnabled(false);

        scheduler.advance(TICK_MS * 10);

        assertEquals(4, target.current);
        assertFalse(autoScroll.isEnabled());
        assertEquals(0, scheduler.pending());
    }

    @Test
    public void aKeyWhenDisabledDoesNothing() {
        target.max = 100;
        autoScroll = UtubotAutoScroll.of(scheduler, () -> SPEED_PX_PER_SEC, target);

        autoScroll.keyPressed();

        assertEquals(0, scheduler.pending());
    }

    @Test
    public void cancelStopsItAndForgetsIt() {
        enabled();

        scheduler.advance(TICK_MS);
        autoScroll.cancel();

        scheduler.advance(TICK_MS * 10);

        assertEquals(4, target.current);
        assertFalse(autoScroll.isEnabled());
    }

    private static final class Target implements UtubotAutoScroll.ScrollTarget {
        int current;
        int max;

        @Override
        public int current() {
            return current;
        }

        @Override
        public int max() {
            return max;
        }

        @Override
        public void moveTo(int offset) {
            current = offset;
        }
    }
}
