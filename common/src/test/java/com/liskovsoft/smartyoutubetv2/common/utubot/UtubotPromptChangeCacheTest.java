package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import androidx.annotation.Nullable;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * A prompt import, refresh or default change drops the ready summaries of the session and of the disk. A summary read or request that
 * was started before the change and completes after it is neither kept nor shown.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotPromptChangeCacheTest {
    private static final int WAIT_MS = 5000;
    private static final String PROMPT_LIST = "{\"default\":\"builtin/tldr\",\"sets\":[{\"id\":\"builtin\",\"name\":\"Built-in\","
            + "\"prompts\":[{\"id\":\"tldr\",\"key\":\"builtin/tldr\",\"label\":\"TL;DR\"}]}]}";
    private static final String READY_ID = "readyAAAAAA";
    private static final String GATED_ID = "gatedBBBBBB";
    private static final String SLOW_ID = "slowCCCCCCC";
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotSettings mSettings;
    private UtubotManager mManager;
    private GatedDiskCache mDisk;
    private final AtomicInteger mReadySummaryCalls = new AtomicInteger();
    private final CountDownLatch mSlowArrived = new CountDownLatch(1);
    private final CountDownLatch mSlowMayAnswer = new CountDownLatch(1);

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/health", request -> new TinyHttpServer.Response(200, "{\"ok\":true,\"version\":\"1.0\"}"));
        mServer.on("/v1/prompts", request -> {
            if (request.method.equals("GET") && request.path.equals("/v1/prompts")) {
                return new TinyHttpServer.Response(200, PROMPT_LIST);
            }

            return new TinyHttpServer.Response(200, "{\"id\":\"demo\",\"name\":\"Demo\",\"prompts\":[]}");
        });
        mServer.on("/v1/videos/" + READY_ID + "/summary", request -> {
            mReadySummaryCalls.incrementAndGet();
            return new TinyHttpServer.Response(200, "{\"video_id\":\"" + READY_ID + "\",\"status\":\"ready\",\"text\":\"- one\"}");
        });
        mServer.on("/v1/videos/" + GATED_ID + "/summary", request -> new TinyHttpServer.Response(200,
                "{\"video_id\":\"" + GATED_ID + "\",\"status\":\"ready\",\"text\":\"- fresh\"}"));
        mServer.on("/v1/videos/" + SLOW_ID + "/summary", request -> {
            mSlowArrived.countDown();
            mSlowMayAnswer.await(WAIT_MS, TimeUnit.MILLISECONDS);
            return new TinyHttpServer.Response(200, "{\"video_id\":\"" + SLOW_ID + "\",\"status\":\"ready\",\"text\":\"- from the old prompts\"}");
        });

        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mSettings = UtubotSettings.instance(mActivity);
        mSettings.setUrl(backend());
        mSettings.setToken("token");
        mDisk = new GatedDiskCache(new File(mFolder.getRoot(), UtubotDiskCache.DIRECTORY), System::currentTimeMillis);
        mManager = new UtubotManager(mActivity, mSettings, mDisk);
    }

    @After
    public void stop() {
        mSlowMayAnswer.countDown();
        mDisk.releaseEveryRead();
        mServer.stop();
        mSettings.setToken("");
        mSettings.setUrl("");
    }

    private String backend() {
        return "http://127.0.0.1:" + mServer.getPort();
    }

    private String scope() {
        return UtubotDiskCache.scopeOf(backend(), "token", "1.0");
    }

    private static Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        video.title = "Title";

        return video;
    }

    private static Summary summary(String id, String text) {
        Summary summary = new Summary();
        summary.videoId = id;
        summary.status = UtubotModels.STATUS_READY;
        summary.prompt = "builtin/tldr";
        summary.text = text;
        summary.source = "captions";

        return summary;
    }

    @Nullable
    private Summary storedSummary(String videoId) {
        UtubotDiskCache restarted = new UtubotDiskCache(new File(mFolder.getRoot(), UtubotDiskCache.DIRECTORY), System::currentTimeMillis);
        restarted.useScope(scope());
        return restarted.getSummary(videoId, "panel");
    }

    private Summary ask(String id) {
        return mManager.summaryObserve(video(id), "panel").blockingFirst();
    }

    private void await(CountDownLatch latch) throws InterruptedException {
        assertTrue("The call did not finish", latch.await(WAIT_MS, TimeUnit.MILLISECONDS));
    }

    @Test
    public void everyPromptChangeDropsTheKeptSummary() {
        ask(READY_ID);

        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNotNull(storedSummary(READY_ID));

        mManager.refreshPromptsObserve().blockingFirst();

        assertNull("a prompt refresh must drop the session's summary", mManager.getCachedSummary(READY_ID, "panel"));
        assertNull("a prompt refresh must drop the disk's summary", storedSummary(READY_ID));

        int afterRefresh = mReadySummaryCalls.get();
        ask(READY_ID);

        assertEquals("the dropped summary must not be served without asking the backend", afterRefresh + 1, mReadySummaryCalls.get());
        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNotNull(storedSummary(READY_ID));

        mManager.importPromptsObserve("https://sets.example.com/p.json").blockingFirst();

        assertNull("a prompt import must drop the session's summary", mManager.getCachedSummary(READY_ID, "panel"));
        assertNull("a prompt import must drop the disk's summary", storedSummary(READY_ID));

        int afterImport = mReadySummaryCalls.get();
        ask(READY_ID);

        assertEquals("the dropped summary must not be served without asking the backend", afterImport + 1, mReadySummaryCalls.get());
        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNotNull(storedSummary(READY_ID));

        mManager.setDefaultPromptObserve("builtin/tldr").blockingFirst();

        assertNull("a default prompt change must drop the session's summary", mManager.getCachedSummary(READY_ID, "panel"));
        assertNull("a default prompt change must drop the disk's summary", storedSummary(READY_ID));

        int afterDefault = mReadySummaryCalls.get();
        ask(READY_ID);

        assertEquals("the dropped summary must not be served without asking the backend", afterDefault + 1, mReadySummaryCalls.get());
    }

    @Test
    public void aStoredSummaryReadThatStartedBeforeAPromptChangeIsNeitherKeptNorShown() throws Exception {
        mDisk.useScope(scope());
        mDisk.putSummary("panel", summary(GATED_ID, "- from the old prompts"));
        mDisk.gateSummaryRead();

        List<Summary> shown = Collections.synchronizedList(new ArrayList<>());
        CountDownLatch finished = new CountDownLatch(1);
        mManager.summaryObserve(video(GATED_ID), "panel").subscribe(shown::add, error -> finished.countDown(), finished::countDown);
        mDisk.waitForSummaryRead();

        // The prompts are refreshed while the disk read has the stored answer but has not returned it yet
        mManager.refreshPromptsObserve().blockingFirst();
        mDisk.letSummaryReadFinish();
        await(finished);

        assertEquals("the stored answer of the old prompts must not be shown", 0, shown.size());
        assertNull("the stored answer of the old prompts must not be kept", mManager.getCachedSummary(GATED_ID, "panel"));
        assertNull("the stored answer of the old prompts must not survive on disk", storedSummary(GATED_ID));
    }

    @Test
    public void aSummaryAnswerThatArrivedAfterAPromptChangeIsNeitherKeptNorShown() throws Exception {
        List<Summary> shown = Collections.synchronizedList(new ArrayList<>());
        CountDownLatch finished = new CountDownLatch(1);
        mManager.summaryObserve(video(SLOW_ID), "panel").subscribe(shown::add, error -> finished.countDown(), finished::countDown);
        assertTrue(mSlowArrived.await(WAIT_MS, TimeUnit.MILLISECONDS));

        // The prompts are refreshed while the answer is on the wire
        mManager.refreshPromptsObserve().blockingFirst();
        mSlowMayAnswer.countDown();
        await(finished);

        assertEquals("the answer of the old prompts must not be shown", 0, shown.size());
        assertNull("the answer of the old prompts must not be kept", mManager.getCachedSummary(SLOW_ID, "panel"));
        assertNull("the answer of the old prompts must not land on disk", storedSummary(SLOW_ID));
    }

    /**
     * A disk cache whose summary read returns the stored answer, then waits for the test to release it outside the disk lock, so a
     * prompt change can clear the disk exactly between the read and the write-back.
     */
    private static final class GatedDiskCache extends UtubotDiskCache {
        private final CountDownLatch mSummaryReadEntered = new CountDownLatch(1);
        private final CountDownLatch mSummaryReadMayFinish = new CountDownLatch(1);
        private volatile boolean mGateSummaryRead;

        GatedDiskCache(File root, Clock clock) {
            super(root, clock);
        }

        void gateSummaryRead() {
            mGateSummaryRead = true;
        }

        void waitForSummaryRead() throws InterruptedException {
            assertTrue("the summary disk read did not start", mSummaryReadEntered.await(WAIT_MS, TimeUnit.MILLISECONDS));
        }

        void letSummaryReadFinish() {
            mSummaryReadMayFinish.countDown();
        }

        void releaseEveryRead() {
            mSummaryReadMayFinish.countDown();
        }

        @Override
        @Nullable
        public Summary getSummary(String videoId, @Nullable String promptKey) {
            Summary stored = super.getSummary(videoId, promptKey);

            if (mGateSummaryRead) {
                mSummaryReadEntered.countDown();

                try {
                    mSummaryReadMayFinish.await(WAIT_MS, TimeUnit.MILLISECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }

            return stored;
        }
    }
}
