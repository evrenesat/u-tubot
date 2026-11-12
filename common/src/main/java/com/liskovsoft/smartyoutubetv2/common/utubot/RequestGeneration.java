package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Tells the answer of the latest request from a late one: a request holds the token it began with, and its answer is used only
 * while the token is the current one.
 */
public final class RequestGeneration {
    private final AtomicLong mCurrent = new AtomicLong();

    /**
     * Starts a request: every earlier one is outdated
     */
    public long begin() {
        return mCurrent.incrementAndGet();
    }

    /**
     * Outdates every request in flight
     */
    public void invalidate() {
        mCurrent.incrementAndGet();
    }

    public boolean isCurrent(long token) {
        return mCurrent.get() == token;
    }
}
