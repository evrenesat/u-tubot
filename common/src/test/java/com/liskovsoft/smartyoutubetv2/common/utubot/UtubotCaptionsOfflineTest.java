package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.google.android.exoplayer2.source.MediaSource;
import com.google.android.exoplayer2.source.MergingMediaSource;
import com.google.android.exoplayer2.source.SilenceMediaSource;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCaptionStore.StoredTrack;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * The HQ captions once downloaded belong to the TV: they are offered for their video after a restart (the memory of the app is gone), a
 * change of backend, or with the backend off the air, and a backend that is asked once is not asked again.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCaptionsOfflineTest {
    private static final String VIDEO = "offlineCapA";
    private static final String OTHER_VIDEO = "offlineCapB";
    private static final int WAIT_MS = 5000;
    private static final String VTT = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.360\nAlper merhaba. Merhaba yaşlı dostum.\n";
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotSettings mSettings;
    private UtubotManager mManager;
    private UtubotCaptionStore mStore;
    private final AtomicInteger mAnswers = new AtomicInteger();
    private final AtomicInteger mFiles = new AtomicInteger();
    private volatile boolean mFileFails;

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/videos/" + VIDEO + "/captions", request -> {
            if (request.path.endsWith(".vtt")) {
                mFiles.incrementAndGet();
                return mFileFails ? new TinyHttpServer.Response(500, "{}") : new TinyHttpServer.Response(200, VTT);
            }

            mAnswers.incrementAndGet();
            return new TinyHttpServer.Response(200, "{\"status\":\"ready\",\"tracks\":[{\"lang\":\"tr\",\"label\":\"Turkish (u·tubot)\","
                    + "\"url\":\"/v1/videos/" + VIDEO + "/captions/tr.vtt\"}]}");
        });

        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mSettings = UtubotSettings.instance(mActivity);
        mSettings.setUrl("http://127.0.0.1:" + mServer.getPort());
        mSettings.setToken("token");
        mManager = UtubotManager.instance(mActivity);
        mStore = UtubotCaptionStore.instance(mActivity);
        removeStored(VIDEO);
        removeStored(OTHER_VIDEO);
    }

    @After
    public void stop() {
        mServer.stop();
        removeStored(VIDEO);
        removeStored(OTHER_VIDEO);
        mSettings.setUrl("");
        mSettings.setToken("");
    }

    @Test
    public void readyCaptions_areDownloadedIntoTheStore() throws Exception {
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });

        waitForStored(VIDEO);

        List<StoredTrack> tracks = mStore.tracks(VIDEO);
        assertEquals(1, tracks.size());
        assertEquals("tr", tracks.get(0).lang);
        assertEquals("Turkish (u·tubot)", tracks.get(0).label);
        assertArrayEquals(VTT.getBytes(StandardCharsets.UTF_8), Files.readAllBytes(tracks.get(0).file.toPath()));
    }

    @Test
    public void storedCaptions_areOfferedAfterARestartWithTheBackendOffTheAir() throws Exception {
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });
        waitForStored(VIDEO);

        // The app starts again: nothing is in memory and the backend is gone
        mServer.stop();
        mSettings.setUrl("");
        mSettings.setToken("");
        assertNull(mManager.getCachedCaptions(VIDEO));

        MediaSource source = new SilenceMediaSource(1_000_000);
        MediaSource merged = UtubotCaptions.attach(mActivity, source, VIDEO);

        assertTrue(merged instanceof MergingMediaSource);
        assertEquals(2, children(merged).length);
        assertEquals("u·tubot: Turkish (u·tubot)", UtubotCaptions.getTrackName("utubot:" + VIDEO + ":tr"));
    }

    @Test
    public void storedCaptions_areNotLostByAChangeOfBackend() throws Exception {
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });
        waitForStored(VIDEO);

        mSettings.setUrl("http://127.0.0.1:1");
        mSettings.setToken("another-token");

        assertTrue(mStore.hasTrack(VIDEO, "tr"));
        assertEquals(2, children(UtubotCaptions.attach(mActivity, new SilenceMediaSource(1_000_000), VIDEO)).length);
    }

    @Test
    public void storedCaptions_areNotAskedForAgain() throws Exception {
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });
        waitForStored(VIDEO);
        int answers = mAnswers.get();
        int files = mFiles.get();

        mSettings.setToken("another-token"); // the memory of the app is dropped
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });
        Thread.sleep(300);

        assertEquals(answers, mAnswers.get());
        assertEquals(files, mFiles.get());
    }

    @Test
    public void captionsThatCouldNotBeDownloaded_arePlayedFromTheBackendAndTriedAgain() throws Exception {
        mFileFails = true;
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });
        waitForCached(VIDEO);

        assertFalse(mStore.has(VIDEO));
        assertEquals(2, children(UtubotCaptions.attach(mActivity, new SilenceMediaSource(1_000_000), VIDEO)).length);

        mFileFails = false;
        mSettings.setToken("another-token");
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });

        waitForStored(VIDEO);
    }

    @Test
    public void aVideoWithoutStoredCaptions_isLeftAlone() {
        MediaSource source = new SilenceMediaSource(1_000_000);

        assertSame(source, UtubotCaptions.attach(mActivity, source, OTHER_VIDEO));
        assertSame(source, UtubotCaptions.attach(mActivity, source, null));
    }

    @Test
    public void storedCaptions_areNotDoubledByTheBackendsAnswerOfTheSameTrack() throws Exception {
        mManager.followCaptions(VIDEO, (videoId, captions, requested) -> { });
        waitForStored(VIDEO);
        waitForCached(VIDEO);

        // The track is in the store and in the answer kept in memory
        assertEquals(2, children(UtubotCaptions.attach(mActivity, new SilenceMediaSource(1_000_000), VIDEO)).length);
    }

    private static MediaSource[] children(MediaSource merged) {
        return ReflectionHelpers.getField(merged, "mediaSources");
    }

    private void removeStored(String videoId) {
        // The singleton keeps the folder of the first test
        File dir = new File(mStore.root(), videoId);
        File[] files = dir.listFiles();

        if (files != null) {
            for (File file : files) {
                assertTrue(file.delete());
            }
        }

        dir.delete();
    }

    private void waitForStored(String videoId) throws InterruptedException {
        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (!mStore.has(videoId) && System.currentTimeMillis() < deadline) {
            Thread.sleep(20);
        }

        assertTrue(mStore.has(videoId));
    }

    private void waitForCached(String videoId) throws InterruptedException {
        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (mManager.getCachedCaptions(videoId) == null && System.currentTimeMillis() < deadline) {
            Thread.sleep(20);
        }

        assertNotNull(mManager.getCachedCaptions(videoId));
    }
}
