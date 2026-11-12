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

public class FocusDebouncerTest {
    private static final long DELAY_MS = 1800;
    private final FakeScheduler mScheduler = new FakeScheduler();
    private final List<String> mEvents = new ArrayList<>();
    private long mDelayMs = DELAY_MS;
    private FocusDebouncer mDebouncer;

    @Before
    public void setUp() {
        mDebouncer = new FocusDebouncer(mScheduler, () -> mDelayMs, new FocusDebouncer.Listener() {
            @Override
            public void onPending(String key) {
                mEvents.add("pending:" + key);
            }

            @Override
            public void onSettled(String key) {
                mEvents.add("settled:" + key);
            }
        });
    }

    @Test
    public void settlesOnlyAfterTheWholePause() {
        mDebouncer.focus("a");
        mScheduler.advance(DELAY_MS - 1);
        assertEquals(Arrays.asList("pending:a"), mEvents);

        mScheduler.advance(1);
        assertEquals(Arrays.asList("pending:a", "settled:a"), mEvents);
        assertFalse(mDebouncer.isPending());
        assertEquals("a", mDebouncer.getSettledKey());
    }

    @Test
    public void everyFocusChangeRestartsThePause() {
        mDebouncer.focus("a");
        mScheduler.advance(1500);
        mDebouncer.focus("b");
        mScheduler.advance(1500);
        mDebouncer.focus("c");
        mScheduler.advance(1500);

        assertEquals(Arrays.asList("pending:a", "pending:b", "pending:c"), mEvents);

        mScheduler.advance(300);
        assertEquals(Arrays.asList("pending:a", "pending:b", "pending:c", "settled:c"), mEvents);
    }

    @Test
    public void aHeldKeyNeverSettles() {
        mDebouncer.focus("a");

        for (int i = 0; i < 200; i++) {
            mScheduler.advance(100);
            mDebouncer.touch();
        }

        assertEquals(Arrays.asList("pending:a"), mEvents);

        mScheduler.advance(DELAY_MS);
        assertEquals(Arrays.asList("pending:a", "settled:a"), mEvents);
    }

    @Test
    public void touchWithNothingPendingDoesNothing() {
        mDebouncer.touch();
        mScheduler.advance(DELAY_MS * 2);

        assertTrue(mEvents.isEmpty());
        assertEquals(0, mScheduler.pending());
    }

    @Test
    public void theSameKeyAgainRestartsThePauseWithoutANewPending() {
        mDebouncer.focus("a");
        mScheduler.advance(1000);
        mDebouncer.focus("a");
        mScheduler.advance(1000);

        assertEquals(Arrays.asList("pending:a"), mEvents);

        mScheduler.advance(800);
        assertEquals(Arrays.asList("pending:a", "settled:a"), mEvents);
    }

    @Test
    public void focusOnTheSettledKeyIsIgnored() {
        mDebouncer.focus("a");
        mScheduler.advance(DELAY_MS);
        mEvents.clear();

        mDebouncer.focus("a");
        mScheduler.advance(DELAY_MS * 2);

        assertTrue(mEvents.isEmpty());
    }

    @Test
    public void leavingTheSettledKeyAndComingBackWaitsAgain() {
        mDebouncer.focus("a");
        mScheduler.advance(DELAY_MS);
        mDebouncer.focus("b");
        mDebouncer.focus("a");
        mScheduler.advance(DELAY_MS);

        assertEquals(Arrays.asList("pending:a", "settled:a", "pending:b", "pending:a", "settled:a"), mEvents);
    }

    @Test
    public void nothingFocusedOrCancelDropsThePendingKey() {
        mDebouncer.focus("a");
        mScheduler.advance(1000);
        mDebouncer.focus(null);
        mScheduler.advance(DELAY_MS * 2);

        assertEquals(Arrays.asList("pending:a"), mEvents);
        assertFalse(mDebouncer.isPending());
        assertNull(mDebouncer.getSettledKey());

        mDebouncer.focus("b");
        mDebouncer.cancel();
        mScheduler.advance(DELAY_MS * 2);

        assertEquals(Arrays.asList("pending:a", "pending:b"), mEvents);
    }

    @Test
    public void aChangedDelayAppliesToTheNextPause() {
        mDebouncer.focus("a");
        mScheduler.advance(DELAY_MS);
        mDelayMs = 5000;

        mDebouncer.focus("b");
        mScheduler.advance(4999);
        assertEquals(Arrays.asList("pending:a", "settled:a", "pending:b"), mEvents);

        mScheduler.advance(1);
        assertEquals("settled:b", mEvents.get(mEvents.size() - 1));
    }
}
