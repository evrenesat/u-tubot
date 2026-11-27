package com.liskovsoft.smartyoutubetv2.common.utubot;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class UtubotFailureThrottleTest {
    @Test
    public void sameFailureIsReportedOncePerWindow() {
        UtubotFailureThrottle throttle = new UtubotFailureThrottle();
        assertTrue(throttle.shouldReport("insight", "HTTP 502", 1_000));
        assertFalse(throttle.shouldReport("insight", "HTTP 502", 2_000));
        assertTrue(throttle.shouldReport("insight", "HTTP 502", 1_000 + UtubotFailureThrottle.WINDOW_MS));
    }

    @Test
    public void floodIsCappedPerWindow() {
        UtubotFailureThrottle throttle = new UtubotFailureThrottle();
        for (int i = 0; i < UtubotFailureThrottle.MAX_PER_WINDOW; i++) {
            assertTrue(throttle.shouldReport("op", "m" + i, 5_000));
        }
        assertFalse(throttle.shouldReport("op", "another", 5_000));
    }
}
