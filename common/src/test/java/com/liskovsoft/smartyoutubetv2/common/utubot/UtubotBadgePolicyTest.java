package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotBadgePolicyTest {
    private static final long DELAY_MS = 600;

    @Test
    public void neverShowsOverThePlayerWhateverTheCount() {
        assertFalse(UtubotBadgePolicy.isAllowed(true, 1));
        assertFalse(UtubotBadgePolicy.isAllowed(true, 5));
        assertFalse(UtubotBadgePolicy.isDue(true, 3, 0, 10_000, DELAY_MS));
    }

    @Test
    public void showsElsewhereOnlyWhileSomethingRuns() {
        assertFalse(UtubotBadgePolicy.isAllowed(false, 0));
        assertTrue(UtubotBadgePolicy.isAllowed(false, 1));
    }

    @Test
    public void aQuickRequestNeverFlashesTheBadge() {
        assertFalse(UtubotBadgePolicy.isDue(false, 1, 1_000, 1_599, DELAY_MS));
        assertTrue(UtubotBadgePolicy.isDue(false, 1, 1_000, 1_600, DELAY_MS));
    }
}
