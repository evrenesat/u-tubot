package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.util.function.LongSupplier;

/**
 * Slow self-scrolling of a text area: it moves the content down a small amount every tick at a reading pace that matches its label,
 * stops at the bottom,
 * pauses on any key and resumes after a delay so waiting long enough shows the whole text. The pacing and the pause are a pure state
 * machine driven by the injected scheduler and the view's own scroll state (see {@link #ScrollTarget}), so they are testable without
 * Android. Manual Up and Down still scroll by hand; every such key just restarts the resume delay.
 */
public final class UtubotAutoScroll {
    /** How often one small step is taken: small enough for a smooth crawl. */
    private static final long TICK_MS = 40;
    /** How long the self-scrolling waits after a key before it starts again. */
    private static final long DEFAULT_RESUME_MS = 4000;

    /**
     * The scrollable the self-scrolling moves. Adapted by the view: its offsets are the view's own {@code scrollY}.
     */
    public interface ScrollTarget {
        /** The current scroll offset. */
        int current();

        /** The maximum scroll offset; zero or less means the content fits and there is nothing to scroll. */
        int max();

        /** Move to the given scroll offset; the value is already inside {@code [0, max]} by the caller. */
        void moveTo(int offset);
    }

    private final UtubotScheduler mScheduler;
    private final LongSupplier mSpeedPxPerSec;
    private final LongSupplier mResumeAfterMs;
    private final ScrollTarget mTarget;
    private final Runnable mTick = this::tick;
    private boolean mEnabled;
    /** Progress gathered in thousandths of a pixel, so the pace averages exactly to the label instead of rounding each tick. */
    private long mAccumulatedThousandths;

    public UtubotAutoScroll(UtubotScheduler scheduler, LongSupplier speedPxPerSec, LongSupplier resumeAfterMs, ScrollTarget target) {
        mScheduler = scheduler;
        mSpeedPxPerSec = speedPxPerSec;
        mResumeAfterMs = resumeAfterMs;
        mTarget = target;
    }

    /**
     * A shorter resume after a key keeps the reading crawl from being interrupted for long; a fixed value is fine here.
     */
    public static UtubotAutoScroll of(UtubotScheduler scheduler, LongSupplier speedPxPerSec, ScrollTarget target) {
        return new UtubotAutoScroll(scheduler, speedPxPerSec, () -> DEFAULT_RESUME_MS, target);
    }

    /**
     * Turns the self-scrolling on or off. While on it crawls to the bottom; off stops it. Repeatedly on with the same content is a
     * no-op once it is running, so a content change that re-reads the same state does not jump the crawl.
     *
     * @param enabled the content that fits (a {@link #ScrollTarget#max()} of zero) never scrolls, on or off
     */
    public void setEnabled(boolean enabled) {
        if (enabled == mEnabled) {
            return;
        }

        mEnabled = enabled;

        if (enabled) {
            arm();
        } else {
            mScheduler.remove(mTick);
        }
    }

    public boolean isEnabled() {
        return mEnabled;
    }

    /**
     * A key was pressed: pause the self-scrolling and resume after the delay. It stops at once when the content fits, so a key on a
     * short text does not leave a timer that would do nothing.
     */
    public void keyPressed() {
        if (!mEnabled) {
            return;
        }

        if (mTarget.max() <= 0) {
            mScheduler.remove(mTick);
            return;
        }

        mScheduler.remove(mTick);
        mScheduler.postDelayed(mTick, mResumeAfterMs.getAsLong());
    }

    /**
     * Forgets the running crawl: the view is going away.
     */
    public void cancel() {
        mEnabled = false;
        mScheduler.remove(mTick);
    }

    private void arm() {
        if (!mEnabled || mTarget.max() <= 0) {
            return;
        }

        mScheduler.postDelayed(mTick, TICK_MS);
    }

    private void tick() {
        if (!mEnabled) {
            return;
        }

        int max = mTarget.max();

        if (max <= 0) {
            mScheduler.remove(mTick);
            return;
        }

        int current = mTarget.current();

        // Add this tick's share of the pace in thousandths of a pixel, then move the whole pixels it has gathered. Carrying the
        // fraction keeps the average exactly the label - 30, 45 and 60 px/s stay distinct and correct - instead of rounding each
        // tick, which collapsed 30 and 45 to the same 50 px/s and made none match its number.
        mAccumulatedThousandths += mSpeedPxPerSec.getAsLong() * TICK_MS;

        int remaining = max - current;
        int moved = (int) Math.min(mAccumulatedThousandths / 1000L, remaining);
        mAccumulatedThousandths -= (long) moved * 1000L;

        int next = current + moved;

        mTarget.moveTo(next);

        if (next < max) {
            mScheduler.postDelayed(mTick, TICK_MS);
        } else {
            mScheduler.remove(mTick);
        }
    }
}
