package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager.CutUpdate;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import io.reactivex.Observable;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The menu shows the cut list of a video at once and refreshes it in the background: a cache already
 * shown is not rebuilt on a fresh list or a 304 (to keep its place on the TV), only a failure shows it
 * again under a notice.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutsOfflineTest {
    private static final String VIDEO = "abcdefghijk";
    private static final String ETAG = "\"list-1\"";
    private static final String BODY = "{\"configured\":true,\"default_mode\":\"quick\",\"modes\":[],"
            + "\"presets\":[{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\"}]}";
    private static final long WAIT_MS = 3000;
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotManager mManager;

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("http://127.0.0.1:" + mServer.getPort());
        settings.setToken("token");
        mManager = UtubotManager.instance(mActivity);
        mManager.onConnectionChanged(); // start each test without the cuts of the previous one
    }

    @After
    public void stop() {
        mServer.stop();
        UtubotSettings.instance(mActivity).setUrl("");
    }

    /**
     * The cut list with its ETag, or a 304 when the stored ETag matches
     */
    private void answerWithEtag(String videoId) {
        mServer.on("/v1/videos/" + videoId + "/cuts", request -> {
            if (ETAG.equals(request.headers.get("if-none-match"))) {
                return new TinyHttpServer.Response(304, "");
            }

            TinyHttpServer.Response response = new TinyHttpServer.Response(200, BODY);
            response.headers.put("etag", ETAG);
            return response;
        });
    }

    /**
     * Always a fresh list, whatever the If-None-Match: it tests that an open menu is not rebuilt on success
     */
    private void answerFresh(String videoId) {
        mServer.on("/v1/videos/" + videoId + "/cuts", request -> {
            TinyHttpServer.Response response = new TinyHttpServer.Response(200, BODY);
            response.headers.put("etag", ETAG);
            return response;
        });
    }

    private void block(String videoId) {
        mServer.on("/v1/videos/" + videoId + "/cuts", request -> new TinyHttpServer.Response(500, "{}"));
    }

    /**
     * Collects the emissions of one `cutsObserve` call off the Rx threads
     */
    private static final class Collector {
        final List<CutUpdate> updates = Collections.synchronizedList(new ArrayList<>());
        volatile Throwable error;
        volatile boolean terminal;
    }

    private Collector observe(String videoId) {
        Collector collector = new Collector();
        Observable<CutUpdate> observe = mManager.cutsObserve(videoId, null);
        observe.subscribe(collector.updates::add, error -> {
            collector.error = error;
            collector.terminal = true;
        }, () -> collector.terminal = true);
        return collector;
    }

    private static List<CutUpdate> waitUntil(int count, Collector collector) {
        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (System.currentTimeMillis() < deadline) {
            synchronized (collector.updates) {
                if (collector.updates.size() >= count) {
                    return new ArrayList<>(collector.updates);
                }
            }

            try {
                Thread.sleep(10);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                break;
            }
        }

        return new ArrayList<>(collector.updates);
    }

    private static void waitTerminal(Collector collector) {
        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (!collector.terminal && System.currentTimeMillis() < deadline) {
            try {
                Thread.sleep(10);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    private static void settle() {
        try {
            Thread.sleep(200);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Opens the cache with the real flow: the first (cache-less) load shows the fresh list and keeps it
     */
    private void seedCache(String videoId) {
        answerWithEtag(videoId);
        Collector collector = observe(videoId);
        waitUntil(1, collector);
        assertNotNull(mManager.getCuts(videoId));
    }

    private static Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        return video;
    }

    @Test
    public void theFreshListIsShownWithoutAPreviousCache() {
        answerFresh(VIDEO);
        Collector collector = observe(VIDEO);

        List<CutUpdate> values = waitUntil(1, collector);
        assertEquals(1, values.size());
        assertTrue(values.get(0).render);
        assertFalse(values.get(0).stale);
        assertNotNull(mManager.getCuts(VIDEO));
    }

    @Test
    public void aCacheIsShownAtOnceAndNotRebuiltOnAFreshList() {
        answerFresh(VIDEO);
        seedCache(VIDEO);
        Collector collector = observe(VIDEO);

        List<CutUpdate> values = waitUntil(1, collector);
        settle();

        assertEquals(1, values.size()); // the refresh succeeded but did not rebuild the open menu
        assertTrue(values.get(0).render);
        assertFalse(values.get(0).stale);
        assertFalse(mManager.cutsLastFailed(VIDEO));
    }

    @Test
    public void aFreshListThatDiffersFromTheCacheRebuildsTheMenu() {
        answerWithEtag(VIDEO);
        seedCache(VIDEO);
        mServer.on("/v1/videos/" + VIDEO + "/cuts", request -> {
            TinyHttpServer.Response response = new TinyHttpServer.Response(200, BODY);
            response.headers.put("etag", "\"changed\"");
            return response;
        });
        Collector collector = observe(VIDEO);

        List<CutUpdate> values = waitUntil(2, collector);

        assertEquals(2, values.size());
        assertFalse(values.get(1).stale);
    }

    @Test
    public void a304DoesNotRebuildTheOpenMenu() {
        answerWithEtag(VIDEO);
        seedCache(VIDEO);
        Collector collector = observe(VIDEO);

        List<CutUpdate> values = waitUntil(1, collector);
        settle();

        assertEquals(1, values.size());
        assertTrue(values.get(0).render);
    }

    @Test
    public void aFailureShowsTheCacheUnderANoticeAgain() {
        answerWithEtag(VIDEO);
        seedCache(VIDEO);
        block(VIDEO);
        Collector collector = observe(VIDEO);

        List<CutUpdate> values = waitUntil(2, collector);
        assertEquals(2, values.size());
        assertTrue(values.get(0).render);
        assertFalse(values.get(0).stale);
        assertTrue(values.get(1).render);
        assertTrue(values.get(1).stale);
        assertTrue(mManager.cutsLastFailed(VIDEO));
    }

    @Test
    public void aFailureWithoutACacheErrors() {
        block(VIDEO);
        Collector collector = observe(VIDEO);

        waitTerminal(collector);

        assertNotNull(collector.error);
        assertTrue(collector.updates.isEmpty());
    }

    @Test
    public void aCutListKeptOnDiskIsShownAfterAManagerRestart() {
        mServer.on("/v1/health", request -> new TinyHttpServer.Response(200, "{\"ok\":true,\"version\":\"1.0\"}"));
        mServer.on("/v1/videos/" + VIDEO + "/summary",
                request -> new TinyHttpServer.Response(200, "{\"video_id\":\"" + VIDEO + "\",\"status\":\"ready\",\"text\":\"- one\",\"source\":\"asr\"}"));

        // The disk scope opens and the first refresh writes the list to disk
        mManager.summaryObserve(video(VIDEO), "panel").blockingFirst();
        answerWithEtag(VIDEO);

        Collector first = observe(VIDEO);
        waitUntil(1, first);
        assertNotNull(mManager.getCuts(VIDEO));

        // A restart: the in-memory cache is gone, the disk is not
        mManager.onConnectionChanged();
        assertNull(mManager.getCuts(VIDEO));

        // The disk scope reloads the cuts it held
        mManager.summaryObserve(video(VIDEO), "panel").blockingFirst();
        assertNotNull(mManager.getCuts(VIDEO));

        // The server is down now: the reloaded cache is shown at once, without a notice
        block(VIDEO);
        Collector collector = observe(VIDEO);

        List<CutUpdate> values = waitUntil(1, collector);
        CutUpdate update = values.get(0);
        assertTrue(update.render);
        assertFalse(update.stale);
    }
}
