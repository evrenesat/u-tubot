package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Counts the u-tubot requests in flight, for the working indicator (see UtubotBadgeController). Listeners are called on the
 * thread that began or ended the request.
 */
public final class UtubotBusyTracker {
    public interface Listener {
        void onCountChanged(int count);
    }

    public interface IoCall<T> {
        T call() throws IOException;
    }

    private static final UtubotBusyTracker sInstance = new UtubotBusyTracker();
    private final List<Listener> mListeners = new CopyOnWriteArrayList<>();
    private int mCount;

    public static UtubotBusyTracker instance() {
        return sInstance;
    }

    public void begin() {
        change(1);
    }

    public void end() {
        change(-1);
    }

    /**
     * Runs the call and counts it as a request in flight, whatever its end
     */
    public <T> T track(IoCall<T> call) throws IOException {
        begin();

        try {
            return call.call();
        } finally {
            end();
        }
    }

    public synchronized int getCount() {
        return mCount;
    }

    public boolean isBusy() {
        return getCount() > 0;
    }

    public void addListener(Listener listener) {
        mListeners.add(listener);
    }

    public void removeListener(Listener listener) {
        mListeners.remove(listener);
    }

    private void change(int delta) {
        int count;

        synchronized (this) {
            int next = Math.max(0, mCount + delta);

            if (next == mCount) {
                return;
            }

            mCount = next;
            count = next;
        }

        for (Listener listener : new ArrayList<>(mListeners)) {
            listener.onCountChanged(count);
        }
    }
}
