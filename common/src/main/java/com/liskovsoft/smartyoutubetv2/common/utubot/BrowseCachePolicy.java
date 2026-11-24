package com.liskovsoft.smartyoutubetv2.common.utubot;

public final class BrowseCachePolicy {
    public static final int DEFAULT_REFRESH_MINUTES = 10;
    public static final int[] REFRESH_MINUTES_CHOICES = {5, 10, 20, 30, 60};
    private static final long MILLIS_PER_MINUTE = 60_000;

    private BrowseCachePolicy() {
    }

    public static boolean isChoice(int minutes) {
        for (int choice : REFRESH_MINUTES_CHOICES) {
            if (choice == minutes) {
                return true;
            }
        }

        return false;
    }

    public static int clampMinutes(int minutes) {
        return isChoice(minutes) ? minutes : DEFAULT_REFRESH_MINUTES;
    }

    public static boolean isStale(long loadedAtMs, long lastAttemptMs, long nowMs, int minutes) {
        long lastMs = Math.max(loadedAtMs, lastAttemptMs);

        return lastMs <= 0 || nowMs - lastMs >= clampMinutes(minutes) * MILLIS_PER_MINUTE;
    }

    public static boolean matchesIdentity(String stored, String current) {
        return stored != null && current != null && stored.equals(current);
    }
}
