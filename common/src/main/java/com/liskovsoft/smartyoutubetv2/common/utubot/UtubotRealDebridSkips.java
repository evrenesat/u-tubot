package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;

import java.util.ArrayList;
import java.util.List;

/**
 * A hand-written list of skip ranges, fed through the sponsor block to prove cut-style playback of a Real-Debrid stream in the spike (no
 * director's cut is built): paste a few "start,end" ranges and the player skips them like sponsor segments.
 *
 * <p>A range is two numbers of a "start,end" pair, seconds by default, an {@code ms} suffix for milliseconds; ranges are separated by a
 * comma run (more than one comma), a semicolon or a newline. "30,90;600,720" skips 30-90 s and 10-12 min. Each range becomes one
 * {@link SponsorSegment} of {@link #CATEGORY} with a skip action.
 */
public final class UtubotRealDebridSkips {
    /** The category the hand-written ranges are filed under, so the sponsor block can be told to skip them. */
    public static final String CATEGORY = "real-debrid";

    private UtubotRealDebridSkips() {
    }

    /**
     * The ranges of a hand-written spec, in order. Empty (never null) for a blank or malformed spec.
     */
    public static List<SponsorSegment> parse(String spec) {
        List<SponsorSegment> result = new ArrayList<>();

        if (spec == null) {
            return result;
        }

        for (String group : spec.split("[;\\n]+")) {
            String range = group.trim();

            if (range.isEmpty()) {
                continue;
            }

            // A comma run (",,") is one separator between the two numbers; a semicolon/newline separates ranges.
            int firstComma = range.indexOf(',');

            if (firstComma < 0) {
                continue;
            }

            long start = parseNumber(range.substring(0, firstComma));
            long end = parseNumber(range.substring(firstComma + 1));

            if (start < 0 || end < start) {
                // A reversed range is written end,start; keep it as-is, order by time. An empty range is dropped.
                long temp = start;
                start = end;
                end = temp;
            }

            if (start < 0 || end <= start) {
                continue;
            }

            result.add(new RangeSegment(start, end));
        }

        return result;
    }

    private static long parseNumber(String text) {
        text = text.trim();

        if (text.isEmpty()) {
            return -1;
        }

        boolean milliseconds = text.toLowerCase().endsWith("ms");

        if (milliseconds) {
            text = text.substring(0, text.length() - 2).trim();
        }

        try {
            double value = Double.parseDouble(text);
            return milliseconds ? (long) value : (long) (value * 1000.0);
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /**
     * The action the sponsor block takes for a hand-written range: skip to the end of the range.
     */
    public static int action() {
        return SponsorBlockData.ACTION_SKIP_ONLY;
    }

    /**
     * A hand-written range, one {@link SponsorSegment}.
     */
    static final class RangeSegment implements SponsorSegment {
        private final long startMs;
        private final long endMs;

        RangeSegment(long startMs, long endMs) {
            this.startMs = startMs;
            this.endMs = endMs;
        }

        @Override
        public long getStartMs() {
            return startMs;
        }

        @Override
        public long getEndMs() {
            return endMs;
        }

        @Override
        public String getCategory() {
            return CATEGORY;
        }

        @Override
        public String getAction() {
            return SponsorSegment.ACTION_SKIP;
        }
    }
}
