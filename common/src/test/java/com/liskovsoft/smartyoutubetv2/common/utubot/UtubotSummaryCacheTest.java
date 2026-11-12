package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * What the app keeps of a summary: only a ready one. The transcript states (no captions, delayed, transcribing) are the answer of the
 * moment: asking again goes to the backend, which may have moved on.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSummaryCacheTest {
    private static final String NEEDS_ID = "needsAAAAAA";
    private static final String DELAYED_ID = "delayedBBBB";
    private static final String BUSY_ID = "busyCCCCCCC";
    private static final String READY_ID = "readyDDDDDD";
    private static final String PENDING_ID = "pendingEEEE";
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotManager mManager;
    private final AtomicInteger mRequests = new AtomicInteger();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        answer(NEEDS_ID, "{\"video_id\":\"" + NEEDS_ID + "\",\"status\":\"needs_transcript\",\"transcript_status\":\"none\",\"can_transcribe\":true," +
                "\"message\":\"No captions.\",\"estimate_s\":120}");
        answer(DELAYED_ID, "{\"video_id\":\"" + DELAYED_ID + "\",\"status\":\"pending\",\"transcript_status\":\"delayed\",\"error\":\"slow\"," +
                "\"retry_after_s\":30}");
        answer(BUSY_ID, "{\"video_id\":\"" + BUSY_ID + "\",\"status\":\"pending\",\"transcript_status\":\"transcribing\",\"progress\":0.4}");
        answer(READY_ID, "{\"video_id\":\"" + READY_ID + "\",\"status\":\"ready\",\"text\":\"- one\",\"source\":\"asr\"}");
        answer(PENDING_ID, "{\"video_id\":\"" + PENDING_ID + "\",\"status\":\"pending\"}");

        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("http://127.0.0.1:" + mServer.getPort());
        settings.setToken("token");
        mManager = UtubotManager.instance(mActivity);
    }

    @After
    public void stop() {
        mServer.stop();
        UtubotSettings.instance(mActivity).setUrl("");
    }

    private void answer(String videoId, String body) {
        mServer.on("/v1/videos/" + videoId + "/summary", request -> {
            mRequests.incrementAndGet();
            return new TinyHttpServer.Response(200, body);
        });
    }

    private static Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        video.title = "Title";

        return video;
    }

    private Summary ask(String id) {
        return mManager.summaryObserve(video(id), "panel").blockingFirst();
    }

    @Test
    public void aVideoWithoutCaptionsIsAskedAgainEveryTime() {
        Summary first = ask(NEEDS_ID);

        assertTrue(first.needsTranscript());
        assertNull(mManager.getCachedSummary(NEEDS_ID, "panel"));

        ask(NEEDS_ID);

        assertEquals(2, mRequests.get());
    }

    @Test
    public void aDelayedAnswerComesBackAtOnceAndIsNotKept() {
        Summary summary = ask(DELAYED_ID);

        assertTrue(summary.isDelayed());
        assertEquals(30, summary.retryAfterSec);
        assertEquals(1, mRequests.get());
        assertNull(mManager.getCachedSummary(DELAYED_ID, "panel"));
    }

    @Test
    public void aRunningTranscriptionComesBackAtOnceAndIsNotKept() {
        Summary summary = ask(BUSY_ID);

        assertTrue(summary.isTranscribing());
        assertEquals(40, summary.progressPercent);
        assertEquals(1, mRequests.get());
        assertNull(mManager.getCachedSummary(BUSY_ID, "panel"));
    }

    @Test
    public void aReadySummaryIsKeptForTheSession() {
        ask(READY_ID);
        Summary again = ask(READY_ID);

        assertEquals(1, mRequests.get());
        assertEquals("- one", again.text);
        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNull(mManager.getCachedSummary(READY_ID, "builtin/tldr"));
    }

    @Test
    public void aPendingJobIsPolledAndNeverKept() {
        Summary summary = ask(PENDING_ID);

        assertTrue(summary.isPending());
        assertFalse(summary.isTransient());
        assertEquals(UtubotManager.MAX_POLLS, mRequests.get());
        assertNull(mManager.getCachedSummary(PENDING_ID, "panel"));
    }
}
