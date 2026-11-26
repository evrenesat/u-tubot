package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * The Real-Debrid spike's hand-written skip list: a few "start,end" ranges become sponsor segments the sponsor block can skip, seconds by
 * default, an {@code ms} suffix for milliseconds, ranges separated by a comma run, a semicolon or a newline.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotRealDebridSkipsTest {

    @Test
    public void parsesRangesInSeconds() throws Exception {
        List<SponsorSegment> segments = UtubotRealDebridSkips.parse("30,90;600,720");

        assertEquals(2, segments.size());
        assertEquals(30_000, segments.get(0).getStartMs());
        assertEquals(90_000, segments.get(0).getEndMs());
        assertEquals(600_000, segments.get(1).getStartMs());
        assertEquals(720_000, segments.get(1).getEndMs());
        assertEquals(UtubotRealDebridSkips.CATEGORY, segments.get(0).getCategory());
        assertEquals(SponsorSegment.ACTION_SKIP, segments.get(0).getAction());
    }

    @Test
    public void aNewlineSeparatesRangesAndWhitespaceIsIgnored() throws Exception {
        List<SponsorSegment> segments = UtubotRealDebridSkips.parse("  10,40 \n 90,120 ");

        assertEquals(2, segments.size());
        assertEquals(10_000, segments.get(0).getStartMs());
        assertEquals(120_000, segments.get(1).getEndMs());
    }

    @Test
    public void anMsSuffixIsTakenAsMilliseconds() throws Exception {
        List<SponsorSegment> segments = UtubotRealDebridSkips.parse("10000ms,30000ms");

        assertEquals(1, segments.size());
        assertEquals(10_000, segments.get(0).getStartMs());
        assertEquals(30_000, segments.get(0).getEndMs());
    }

    @Test
    public void aReversedOrEmptyRangeIsSkipped() throws Exception {
        List<SponsorSegment> segments = UtubotRealDebridSkips.parse("90,30;5,5;; ,");

        assertEquals(1, segments.size());
        assertEquals(30_000, segments.get(0).getStartMs());
        assertEquals(90_000, segments.get(0).getEndMs());
    }

    @Test
    public void aBlankOrMalformedSpecHasNoRanges() throws Exception {
        assertTrue(UtubotRealDebridSkips.parse("").isEmpty());
        assertTrue(UtubotRealDebridSkips.parse(null).isEmpty());
        assertTrue(UtubotRealDebridSkips.parse("no numbers here").isEmpty());
    }
}
