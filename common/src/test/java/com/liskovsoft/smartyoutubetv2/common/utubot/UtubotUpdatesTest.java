package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;

/**
 * An update found while the player is open is offered again soon: what the presenter reports reaches the schedule
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotUpdatesTest {
    private final FakeScheduler mScheduler = new FakeScheduler();
    private int mChecks;

    @Before
    public void setUp() {
        UtubotUpdateSchedule schedule = new UtubotUpdateSchedule(mScheduler, () -> {
            mChecks++;
            return true;
        });
        schedule.start();
        mScheduler.advance(UtubotUpdateSchedule.START_DELAY_MS);
        UtubotUpdates.useSchedule(schedule);
    }

    @After
    public void tearDown() {
        UtubotUpdates.useSchedule(null);
    }

    @Test
    public void aDeferredUpdateIsCheckedAgainAfterFiveMinutesNotSixHours() {
        UtubotUpdates.onUpdateDeferred();

        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);

        assertEquals(2, mChecks);
    }

    @Test
    public void theNextScreenBringsTheCheckForward() {
        UtubotUpdates.onUpdateDeferred();
        mScheduler.advance(1_000);

        UtubotUpdates.onScreenAvailable();
        mScheduler.advance(UtubotUpdateSchedule.SETTLE_MS);

        assertEquals(2, mChecks);
    }

    @Test
    public void withoutAScheduleNothingHappens() {
        UtubotUpdates.useSchedule(null);

        UtubotUpdates.onUpdateDeferred();
        UtubotUpdates.onScreenAvailable();
        mScheduler.advance(UtubotUpdateSchedule.RETRY_MS);

        assertEquals("the schedule that was replaced is not moved", 1, mChecks);
    }
}
