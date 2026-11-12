package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class UtubotBusyTrackerTest {
    private final UtubotBusyTracker mTracker = new UtubotBusyTracker();
    private final List<Integer> mCounts = new ArrayList<>();

    @Test
    public void countsTheRequestsInFlight() {
        mTracker.addListener(mCounts::add);

        mTracker.begin();
        mTracker.begin();
        assertEquals(2, mTracker.getCount());
        assertTrue(mTracker.isBusy());

        mTracker.end();
        mTracker.end();

        assertEquals(0, mTracker.getCount());
        assertFalse(mTracker.isBusy());
        assertEquals(Arrays.asList(1, 2, 1, 0), mCounts);
    }

    @Test
    public void anEndWithoutABeginStaysAtZeroAndTellsNobody() {
        mTracker.addListener(mCounts::add);

        mTracker.end();

        assertEquals(0, mTracker.getCount());
        assertTrue(mCounts.isEmpty());
    }

    @Test
    public void trackedCallsEndWhateverTheirResult() throws Exception {
        mTracker.addListener(mCounts::add);

        assertEquals("ok", mTracker.track(() -> {
            assertEquals(1, mTracker.getCount());
            return "ok";
        }));

        try {
            mTracker.track(() -> {
                throw new IOException("down");
            });
            fail();
        } catch (IOException expected) {
            assertEquals("down", expected.getMessage());
        }

        assertEquals(0, mTracker.getCount());
        assertEquals(Arrays.asList(1, 0, 1, 0), mCounts);
    }

    @Test
    public void aRemovedListenerHearsNothing() {
        UtubotBusyTracker.Listener listener = mCounts::add;
        mTracker.addListener(listener);
        mTracker.removeListener(listener);

        mTracker.begin();

        assertTrue(mCounts.isEmpty());
    }

    @Test
    public void countsRequestsFromSeveralThreads() throws Exception {
        List<Thread> threads = new ArrayList<>();

        for (int i = 0; i < 8; i++) {
            Thread thread = new Thread(() -> {
                for (int n = 0; n < 500; n++) {
                    mTracker.begin();
                    mTracker.end();
                }
            });
            threads.add(thread);
            thread.start();
        }

        for (Thread thread : threads) {
            thread.join();
        }

        assertEquals(0, mTracker.getCount());
    }
}
