package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class BrowseCachePolicyTest {
    private static final long MINUTE = 60_000;

    @Test
    public void contentIsFreshUntilTheNamedMinutesPass() {
        assertFalse(BrowseCachePolicy.isStale(10_000, 0, 10_000 + 5 * MINUTE - 1, 5));
        assertTrue(BrowseCachePolicy.isStale(10_000, 0, 10_000 + 5 * MINUTE, 5));
    }

    @Test
    public void withoutAContentTimeTheSectionIsStale() {
        assertTrue(BrowseCachePolicy.isStale(0, 0, 0, 5));
        assertFalse(BrowseCachePolicy.isStale(0, 10_000, 10_000 + 1, 5));
    }

    @Test
    public void aRefreshAttemptCountsAsTheLastLoad() {
        long loaded = 10_000;
        long attempt = loaded + 4 * MINUTE;

        assertFalse(BrowseCachePolicy.isStale(loaded, attempt, loaded + 4 * MINUTE + 1, 5));
        assertTrue(BrowseCachePolicy.isStale(loaded, attempt, loaded + 9 * MINUTE, 5));
    }

    @Test
    public void unknownMinutesFallBackToTheDefault() {
        assertEquals(BrowseCachePolicy.DEFAULT_REFRESH_MINUTES, BrowseCachePolicy.clampMinutes(0));
        assertEquals(BrowseCachePolicy.DEFAULT_REFRESH_MINUTES, BrowseCachePolicy.clampMinutes(-1));
        assertEquals(BrowseCachePolicy.DEFAULT_REFRESH_MINUTES, BrowseCachePolicy.clampMinutes(7));

        for (int choice : BrowseCachePolicy.REFRESH_MINUTES_CHOICES) {
            assertEquals(choice, BrowseCachePolicy.clampMinutes(choice));
            assertTrue(BrowseCachePolicy.isChoice(choice));
        }
    }

    @Test
    public void anotherAccountOrLocaleDoesNotMatch() {
        assertTrue(BrowseCachePolicy.matchesIdentity("en_US|owner", "en_US|owner"));
        assertFalse(BrowseCachePolicy.matchesIdentity("en_US|owner", "tr_TR|owner"));
        assertFalse(BrowseCachePolicy.matchesIdentity("en_US|owner", "en_US|partner"));
        assertFalse(BrowseCachePolicy.matchesIdentity(null, "en_US|owner"));
        assertFalse(BrowseCachePolicy.matchesIdentity("en_US|owner", null));
    }
}
