package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The verdicts of this session, the oldest dropped first. Only ready ones are kept: a pending video is asked again with the next load.
 */
public class VerdictCache {
    public static final int MAX_ENTRIES = 2000;
    private final Map<String, Verdict> mEntries;

    public VerdictCache(int maxEntries) {
        mEntries = new LinkedHashMap<String, Verdict>(16, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<String, Verdict> eldest) {
                return size() > maxEntries;
            }
        };
    }

    @Nullable
    public synchronized Verdict get(String videoId) {
        return videoId == null ? null : mEntries.get(videoId);
    }

    public synchronized void put(Verdict verdict) {
        if (verdict != null && verdict.videoId != null && verdict.isReady()) {
            mEntries.put(verdict.videoId, verdict);
        }
    }

    public synchronized void clear() {
        mEntries.clear();
    }

    public synchronized int size() {
        return mEntries.size();
    }
}
