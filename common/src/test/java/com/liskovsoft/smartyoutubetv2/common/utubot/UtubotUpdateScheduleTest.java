package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Before;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class UtubotUpdateScheduleTest {
    private final FakeScheduler mScheduler = new FakeScheduler();
    private int mChecks;
    private boolean mCanCheck = true;
    private UtubotUpdateSchedule mSchedule;

    @Before
    public void setUp() {
        mSchedule = new UtubotUpdateSchedule(mScheduler, () -> {
            mChecks++;
            return mCanCheck;
        });
    }

    @Test
    public void checksShortlyAfterTheStartThenEverySixHours() {
        mSchedule.start();

        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS - 1);
        assertEquals(0, mChecks);

        mScheduler.advance(1);
        assertEquals(1, mChecks);

        mScheduler.advance(UtubotUpdateSchedule.INTERVAL_MS - 1);
        assertEquals(1, mChecks);
        mScheduler.advance(1);
        assertEquals(2, mChecks);

        mScheduler.advance(UtubotUpdateSchedule.INTERVAL_MS);
        assertEquals(3, mChecks);
    }

    @Test
    public void theIntervalIsSixHours() {
        assertEquals(6 * 60 * 60 * 1000L, UtubotUpdateSchedule.INTERVAL_MS);
    }

    @Test
    public void startingAgainChangesNothing() {
        mSchedule.start();
        mScheduler.advance(10_000);
        mSchedule.start();
        mSchedule.start();

        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS - 10_000);
        assertEquals(1, mChecks);
        assertEquals(1, mScheduler.pending());
    }

    @Test
    public void aCheckThatCantHappenNowIsTriedAgainSoon() {
        mCanCheck = false;
        mSchedule.start();

        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        assertEquals(1, mChecks);

        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(2, mChecks);

        mCanCheck = true;
        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(3, mChecks);

        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(3, mChecks);
    }

    @Test
    public void aFailingCheckDoesNotStopTheSchedule() {
        UtubotUpdateSchedule schedule = new UtubotUpdateSchedule(mScheduler, () -> {
            mChecks++;
            throw new IllegalStateException("boom");
        });
        schedule.start();

        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS + UtubotUpdateSchedule.RETRY_MS);

        assertEquals(2, mChecks);
    }

    @Test
    public void anUpdateThatCouldNotBeShownIsOfferedAgainWithinFiveMinutes() {
        mSchedule.start();
        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        assertEquals(1, mChecks);

        // The check found an update while the player was open
        mSchedule.onUpdateDeferred();

        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS - 1);
        assertEquals(1, mChecks);
        mScheduler.advance(1);
        assertEquals(2, mChecks);
        assertEquals("one pending run only", 1, mScheduler.pending());
    }

    @Test
    public void whenThePlayerClosesAWaitingUpdateIsOfferedAfterAShortRest() {
        mSchedule.start();
        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        mSchedule.onUpdateDeferred();
        mScheduler.advance(60_000);

        mSchedule.onScreenAvailable();

        mScheduler.advance(UtubotUpdateSchedule.SETTLE_MS - 1);
        assertEquals(1, mChecks);
        mScheduler.advance(1);
        assertEquals(2, mChecks);
        assertEquals(1, mScheduler.pending());
    }

    @Test
    public void aScreenComingUpWithNothingWaitingChangesNothing() {
        mSchedule.start();
        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);

        mSchedule.onScreenAvailable();
        mScheduler.advance(UtubotUpdateSchedule.SETTLE_MS * 2);

        assertEquals(1, mChecks);
        mScheduler.advance(UtubotUpdateSchedule.INTERVAL_MS);
        assertEquals(2, mChecks);
    }

    @Test
    public void theScreenNudgeIsUsedUpByTheCheckItBrought() {
        mSchedule.start();
        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        mSchedule.onUpdateDeferred();
        mSchedule.onScreenAvailable();
        mScheduler.advance(UtubotUpdateSchedule.SETTLE_MS);
        assertEquals(2, mChecks);

        // The next screen (a second resume, a dialog closing) doesn't ask for another check
        mSchedule.onScreenAvailable();
        mScheduler.advance(UtubotUpdateSchedule.SETTLE_MS * 2);

        assertEquals(2, mChecks);
    }

    @Test
    public void aWaitingUpdateWhosePlayerIsStillOpenKeepsTryingEveryFiveMinutes() {
        mSchedule.start();
        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        mSchedule.onUpdateDeferred();
        mCanCheck = false;

        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(2, mChecks);
        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(3, mChecks);

        mCanCheck = true;
        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(4, mChecks);
        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals("back to the long interval", 4, mChecks);
    }

    @Test
    public void aDeferralDuringTheCheckItselfStillGetsTheShortRetry() {
        UtubotUpdateSchedule[] holder = new UtubotUpdateSchedule[1];
        holder[0] = new UtubotUpdateSchedule(mScheduler, () -> {
            mChecks++;
            holder[0].onUpdateDeferred();
            return true;
        });
        holder[0].start();

        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        assertEquals(1, mChecks);
        assertEquals(1, mScheduler.pending());

        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);
        assertEquals(2, mChecks);
    }

    @Test
    public void nothingIsScheduledByADeferralBeforeTheStartOrAfterTheStop() {
        mSchedule.onUpdateDeferred();
        mSchedule.onScreenAvailable();
        assertEquals(0, mScheduler.pending());

        mSchedule.start();
        mSchedule.stop();
        mSchedule.onUpdateDeferred();
        mSchedule.onScreenAvailable();
        mScheduler.advance(UtubotUpdateSchedule.INTERVAL_MS);

        assertEquals(0, mChecks);
    }

    @Test
    public void stopCancelsTheChecks() {
        mSchedule.start();
        mSchedule.stop();

        mScheduler.advance(UtubotUpdateSchedule.INTERVAL_MS * 2);

        assertEquals(0, mChecks);
    }
}
