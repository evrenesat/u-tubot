package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

public class VerdictCacheTest {
    private static Verdict verdict(String id, String status) {
        Verdict verdict = new Verdict();
        verdict.videoId = id;
        verdict.status = status;
        return verdict;
    }

    @Test
    public void keepsReadyVerdictsOnly() {
        VerdictCache cache = new VerdictCache(10);

        cache.put(verdict("a", "ready"));
        cache.put(verdict("b", "pending"));

        assertNotNull(cache.get("a"));
        assertNull(cache.get("b"));
        assertEquals(1, cache.size());
    }

    @Test
    public void dropsTheLeastRecentlyUsed() {
        VerdictCache cache = new VerdictCache(2);

        cache.put(verdict("a", "ready"));
        cache.put(verdict("b", "ready"));
        cache.get("a");
        cache.put(verdict("c", "ready"));

        assertNotNull(cache.get("a"));
        assertNull(cache.get("b"));
        assertNotNull(cache.get("c"));
    }

    @Test
    public void ignoresNullAndUnknown() {
        VerdictCache cache = new VerdictCache(2);

        cache.put(null);
        cache.put(verdict(null, "ready"));

        assertNull(cache.get(null));
        assertNull(cache.get("x"));
        assertEquals(0, cache.size());
    }
}
