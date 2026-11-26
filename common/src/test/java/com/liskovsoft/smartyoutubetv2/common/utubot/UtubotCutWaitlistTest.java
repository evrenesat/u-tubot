package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * The waiting list of the cuts this device ordered (issue 96): it survives a restart and keeps one row per request.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutWaitlistTest {
    private final FakeCutWaitlistStore mStore = new FakeCutWaitlistStore();

    @Test
    public void anOrderedCut_isKeptForTheNextStart() {
        UtubotCutWaitlist waitlist = new UtubotCutWaitlist(mStore);
        waitlist.add(new Entry("cut1", "Lqig_Ui9Hh0", "The demo", 1000));

        UtubotCutWaitlist restarted = new UtubotCutWaitlist(mStore);
        List<Entry> entries = restarted.entries();

        assertEquals(1, entries.size());
        assertEquals("cut1", entries.get(0).requestId);
        assertEquals("Lqig_Ui9Hh0", entries.get(0).videoId);
        assertEquals("The demo", entries.get(0).title);
        assertEquals(1000, entries.get(0).orderedAtMs);
    }

    @Test
    public void theSameRequestIsOneRow() {
        UtubotCutWaitlist waitlist = new UtubotCutWaitlist(mStore);
        waitlist.add(new Entry("cut1", "Lqig_Ui9Hh0", "First title", 1000));
        waitlist.add(new Entry("cut1", "Lqig_Ui9Hh0", "Second title", 2000));

        List<Entry> entries = waitlist.entries();

        assertEquals(1, entries.size());
        assertEquals("Second title", entries.get(0).title);
        assertEquals(2000, entries.get(0).orderedAtMs);
    }

    @Test
    public void aReadyOrFailedRequestLeavesTheList() {
        UtubotCutWaitlist waitlist = new UtubotCutWaitlist(mStore);
        waitlist.add(new Entry("cut1", "Lqig_Ui9Hh0", "The demo", 1000));
        waitlist.add(new Entry("cut2", "jNQXAC9IVRw", "The talk", 2000));

        waitlist.remove("cut1");

        assertEquals(1, waitlist.entries().size());
        assertEquals("cut2", waitlist.entries().get(0).requestId);
        assertEquals(1, new UtubotCutWaitlist(mStore).entries().size());
    }

    @Test
    public void theListKeepsTheNewestOrders() {
        UtubotCutWaitlist waitlist = new UtubotCutWaitlist(mStore);

        for (int i = 0; i < UtubotCutWaitlist.MAX_ENTRIES + 3; i++) {
            waitlist.add(new Entry("cut" + i, "Lqig_Ui9Hh0", "Title " + i, i));
        }

        List<Entry> entries = waitlist.entries();

        assertEquals(UtubotCutWaitlist.MAX_ENTRIES, entries.size());
        assertEquals("cut3", entries.get(0).requestId);
        assertEquals("cut" + (UtubotCutWaitlist.MAX_ENTRIES + 2), entries.get(entries.size() - 1).requestId);
    }

    @Test
    public void clearingTheList_stopsEveryWait() {
        UtubotCutWaitlist waitlist = new UtubotCutWaitlist(mStore);
        waitlist.add(new Entry("cut1", "Lqig_Ui9Hh0", "The demo", 1000));
        waitlist.add(new Entry("cut2", "jNQXAC9IVRw", "The talk", 2000));

        waitlist.clear();

        assertTrue(waitlist.entries().isEmpty());
        assertTrue(new UtubotCutWaitlist(mStore).entries().isEmpty());
    }

    @Test
    public void aStoredRowWithoutItsIdsIsSkipped() {
        List<Entry> entries = UtubotCutWaitlist.decode("[{\"id\":\"cut1\",\"video\":\"Lqig_Ui9Hh0\",\"title\":\"The demo\",\"at\":5},"
                + "{\"title\":\"no ids\"}]");

        assertEquals(1, entries.size());
        assertEquals("cut1", entries.get(0).requestId);
        assertEquals("The demo", entries.get(0).title);
    }

    @Test
    public void aCorruptStoredListReadsAsEmpty() {
        assertTrue(UtubotCutWaitlist.decode("not json").isEmpty());
    }
}
