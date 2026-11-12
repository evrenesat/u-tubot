package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * A clock the test moves: tasks run when advance() reaches their time
 */
final class FakeScheduler implements UtubotScheduler {
    private static final class Task {
        final Runnable runnable;
        final long dueMs;

        Task(Runnable runnable, long dueMs) {
            this.runnable = runnable;
            this.dueMs = dueMs;
        }
    }

    private final List<Task> mTasks = new ArrayList<>();
    private long mNowMs;

    @Override
    public void postDelayed(Runnable task, long delayMs) {
        mTasks.add(new Task(task, mNowMs + delayMs));
    }

    @Override
    public void remove(Runnable task) {
        mTasks.removeIf(entry -> entry.runnable == task);
    }

    long now() {
        return mNowMs;
    }

    int pending() {
        return mTasks.size();
    }

    void advance(long ms) {
        long target = mNowMs + ms;

        while (true) {
            Task next = mTasks.stream().filter(task -> task.dueMs <= target).min(Comparator.comparingLong(task -> task.dueMs)).orElse(null);

            if (next == null) {
                break;
            }

            mTasks.remove(next);
            mNowMs = Math.max(mNowMs, next.dueMs);
            next.runnable.run();
        }

        mNowMs = target;
    }
}
