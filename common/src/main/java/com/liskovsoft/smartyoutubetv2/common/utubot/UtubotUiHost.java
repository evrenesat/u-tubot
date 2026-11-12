package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.os.SystemClock;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * The bridge between the video menu (common) and the screen that shows the Summary view or the AI answer (tv): the menu closes its
 * dialog and posts a request, the screen underneath takes it when it resumes. A screen that can show them (the browse, search and
 * channel screens) registers as a host; the player is not one.
 */
public final class UtubotUiHost {
    public interface Host {
        /**
         * A request was posted while the screen is up
         */
        void onOpenRequest();
    }

    private static final UtubotOpenRequests sRequests = new UtubotOpenRequests();
    private static final AtomicInteger sHostCount = new AtomicInteger();
    private static volatile Host sResumedHost;
    private static volatile boolean sIsPlayerScreen;

    private UtubotUiHost() {
    }

    public static void onHostCreated() {
        sHostCount.incrementAndGet();
    }

    public static void onHostDestroyed() {
        sHostCount.updateAndGet(count -> Math.max(0, count - 1));
    }

    public static void setResumedHost(@Nullable Host host) {
        sResumedHost = host;
    }

    public static void clearResumedHost(Host host) {
        if (sResumedHost == host) {
            sResumedHost = null;
        }
    }

    /**
     * The last screen that came up, apart from dialogs, is the player
     */
    public static void setPlayerScreen(boolean isPlayer) {
        sIsPlayerScreen = isPlayer;
    }

    /**
     * A screen can show the Summary view or the answer: the menu offers them and posts requests. Not over the player.
     */
    public static boolean canOpen() {
        return sHostCount.get() > 0 && !sIsPlayerScreen;
    }

    public static void request(UtubotOpenRequests.Kind kind, Video video) {
        sRequests.post(kind, video, SystemClock.uptimeMillis());
        Host host = sResumedHost;

        if (host != null) {
            host.onOpenRequest();
        }
    }

    @Nullable
    public static UtubotOpenRequests.Request take() {
        return sRequests.take(SystemClock.uptimeMillis());
    }
}
