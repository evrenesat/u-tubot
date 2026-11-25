package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;

import java.util.ArrayList;
import java.util.List;

/**
 * An in-memory waiting list's storage: what a restart of the app would read
 */
final class FakeCutWaitlistStore implements UtubotCutWaitlist.Store {
    private List<Entry> mEntries = new ArrayList<>();

    @Override
    public List<Entry> load() {
        return new ArrayList<>(mEntries);
    }

    @Override
    public void save(List<Entry> entries) {
        mEntries = new ArrayList<>(entries);
    }
}
