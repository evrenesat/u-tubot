package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.os.Looper;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SimpleMediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import io.reactivex.Observable;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * A disk read that started for one backend is still in flight when the user selects another. The old call must neither open its scope
 * after the switch (it deletes the other scopes' directories) nor put its answer into the cleared memory or the new scope.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotConnectionDiskRaceTest {
    private static final int WAIT_MS = 5000;
    private static final long MAIN_LOOPER_POLL_MS = 20;
    private static final String OLD_TOKEN = "old-token";
    private static final String NEW_TOKEN = "new-token";
    private static final String VIDEO_ID = "raceAAAAAAA";
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotSettings mSettings;
    private UtubotManager mManager;
    private GatedDiskCache mDisk;
    private final AtomicInteger mNewSummaryCalls = new AtomicInteger();
    private final AtomicInteger mNewAssessCalls = new AtomicInteger();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/health", request -> new TinyHttpServer.Response(200, "{\"ok\":true,\"version\":\"1.0\"}"));
        mServer.on("/v1/videos/" + VIDEO_ID + "/summary", request -> {
            if (isBearer(request, NEW_TOKEN)) {
                mNewSummaryCalls.incrementAndGet();
                return new TinyHttpServer.Response(200, "{\"video_id\":\"" + VIDEO_ID + "\",\"status\":\"ready\",\"text\":\"- fresh from the new backend\"}");
            }

            return new TinyHttpServer.Response(200, "{\"video_id\":\"" + VIDEO_ID + "\",\"status\":\"ready\",\"text\":\"- from the old backend\"}");
        });
        mServer.on("/v1/assess", request -> {
            if (isBearer(request, NEW_TOKEN)) {
                mNewAssessCalls.incrementAndGet();
            }

            return new TinyHttpServer.Response(200, "{\"results\":[{\"video_id\":\"" + VIDEO_ID + "\",\"status\":\"ready\",\"action\":\"none\"}]}");
        });

        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mSettings = UtubotSettings.instance(mActivity);
        mSettings.setUrl(backend());
        mSettings.setToken(OLD_TOKEN);
        mDisk = new GatedDiskCache(new File(mFolder.getRoot(), UtubotDiskCache.DIRECTORY), System::currentTimeMillis);
        mManager = new UtubotManager(mActivity, mSettings, mDisk);
    }

    @After
    public void stop() {
        mDisk.releaseEveryRead();
        mServer.stop();
        mSettings.setToken("");
        mSettings.setUrl("");
    }

    private String backend() {
        return "http://127.0.0.1:" + mServer.getPort();
    }

    private String scope(String token) {
        return UtubotDiskCache.scopeOf(backend(), token, "1.0");
    }

    private static boolean isBearer(TinyHttpServer.Request request, String token) {
        return ("Bearer " + token).equals(request.headers.get("authorization"));
    }

    private static Verdict verdict(String id, String action) {
        Verdict verdict = new Verdict();
        verdict.videoId = id;
        verdict.status = "ready";
        verdict.action = action;

        return verdict;
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

    private static Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        video.title = "Video " + id;
        video.author = "Channel";
        video.secondTitle = "Channel • 5K views • 3 weeks ago";

        return video;
    }

    private void await(CountDownLatch latch) throws InterruptedException {
        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (!latch.await(MAIN_LOOPER_POLL_MS, TimeUnit.MILLISECONDS)) {
            ShadowLooper.idleMainLooper();
            assertTrue("The call did not finish", System.currentTimeMillis() < deadline);
        }
    }

    private void resolve(Video video) throws InterruptedException {
        CountDownLatch finished = new CountDownLatch(1);
        Observable<Boolean> resolved = mManager.resolve(Collections.singletonList(createRow(video)), createSection());
        resolved.subscribe(done -> {}, error -> finished.countDown(), finished::countDown);

        await(finished);
    }

    @Test
    public void aStaleVerdictDiskReadDoesNotReopenItsScopeOrFillTheNewMemory() throws Exception {
        mDisk.useScope(scope(OLD_TOKEN));
        mDisk.putVerdicts(Collections.singletonList(verdict(VIDEO_ID, UtubotModels.ACTION_HIDE)));
        mDisk.gateVerdictRead();

        CountDownLatch oldFinished = new CountDownLatch(1);
        mManager.resolve(Collections.singletonList(createRow(video(VIDEO_ID))), createSection())
                .subscribe(done -> {}, error -> oldFinished.countDown(), oldFinished::countDown);
        mDisk.waitForVerdictRead();

        // The user imports a setup for another backend while the old connection's disk read is still in flight
        mSettings.setToken(NEW_TOKEN);
        mDisk.letVerdictReadFinish();
        await(oldFinished);

        assertEquals("the old call was answered from memory and never asked the new backend", 0, mNewAssessCalls.get());
        assertNull("the old connection's verdict was cleared and must not come back", mManager.getVerdict(VIDEO_ID));

        resolve(video(VIDEO_ID));

        assertEquals(1, mNewAssessCalls.get());
        Verdict current = mManager.getVerdict(VIDEO_ID);
        assertNotNull(current);
        assertEquals(UtubotModels.ACTION_NONE, current.action);

        // The new connection's verdict was stored in its own scope, not the old one's (which is removed now)
        UtubotDiskCache restarted = new UtubotDiskCache(new File(mFolder.getRoot(), UtubotDiskCache.DIRECTORY), System::currentTimeMillis);
        restarted.useScope(scope(NEW_TOKEN));
        List<Verdict> stored = restarted.loadVerdicts();
        assertEquals(1, stored.size());
        assertEquals(VIDEO_ID, stored.get(0).videoId);
        assertEquals(UtubotModels.ACTION_NONE, stored.get(0).action);
    }

    @Test
    public void aStaleSummaryDiskReadIsNotKeptForTheNewConnection() throws Exception {
        mDisk.useScope(scope(OLD_TOKEN));
        mDisk.putSummary("panel", summary(VIDEO_ID, "- from the old backend"));
        mDisk.gateSummaryRead();

        CountDownLatch oldFinished = new CountDownLatch(1);
        mManager.summaryObserve(video(VIDEO_ID), "panel").subscribe(summary -> {}, error -> oldFinished.countDown(), oldFinished::countDown);
        mDisk.waitForSummaryRead();

        // The user imports a setup for another backend while the old connection's disk read is still in flight
        mSettings.setToken(NEW_TOKEN);
        mDisk.letSummaryReadFinish();
        await(oldFinished);

        assertNull("the old connection's summary must not be kept after the switch", mManager.getCachedSummary(VIDEO_ID, "panel"));
        assertEquals(0, mNewSummaryCalls.get());

        Summary fresh = mManager.summaryObserve(video(VIDEO_ID), "panel").blockingFirst();

        assertEquals("- fresh from the new backend", fresh.text);
        assertEquals(1, mNewSummaryCalls.get());
        assertNotNull(mManager.getCachedSummary(VIDEO_ID, "panel"));
    }

    private static BrowseSection createSection() {
        return new BrowseSection(MediaGroup.TYPE_HOME, "Section", BrowseSection.TYPE_GRID, 0);
    }

    private static MediaGroup createRow(Video... videos) {
        return new TestMediaGroup(MediaGroup.TYPE_HOME, videos);
    }

    /**
     * A disk cache whose named read counts down when it starts and waits for the test to release it, so a connection change can land
     * exactly while the read is in flight.
     */
    private static final class GatedDiskCache extends UtubotDiskCache {
        private final CountDownLatch mVerdictReadEntered = new CountDownLatch(1);
        private final CountDownLatch mVerdictReadMayFinish = new CountDownLatch(1);
        private final CountDownLatch mSummaryReadEntered = new CountDownLatch(1);
        private final CountDownLatch mSummaryReadMayFinish = new CountDownLatch(1);
        private volatile boolean mGateVerdictRead;
        private volatile boolean mGateSummaryRead;

        GatedDiskCache(File root, Clock clock) {
            super(root, clock);
        }

        void gateVerdictRead() {
            mGateVerdictRead = true;
        }

        void waitForVerdictRead() throws InterruptedException {
            assertTrue("the verdict disk read did not start", mVerdictReadEntered.await(WAIT_MS, TimeUnit.MILLISECONDS));
        }

        void letVerdictReadFinish() {
            mVerdictReadMayFinish.countDown();
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
            mVerdictReadMayFinish.countDown();
            mSummaryReadMayFinish.countDown();
        }

        @Override
        public synchronized List<Verdict> loadVerdicts() {
            if (mGateVerdictRead) {
                mVerdictReadEntered.countDown();
                await(mVerdictReadMayFinish);
            }

            return super.loadVerdicts();
        }

        @Override
        @androidx.annotation.Nullable
        public synchronized Summary getSummary(String videoId, @androidx.annotation.Nullable String promptKey) {
            if (mGateSummaryRead) {
                mSummaryReadEntered.countDown();
                await(mSummaryReadMayFinish);
            }

            return super.getSummary(videoId, promptKey);
        }

        private static void await(CountDownLatch latch) {
            try {
                latch.await(WAIT_MS, TimeUnit.MILLISECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private static final class TestMediaGroup implements MediaGroup {
        private final int mType;
        private final List<MediaItem> mItems = new ArrayList<>();

        TestMediaGroup(int type, Video... videos) {
            mType = type;

            for (Video video : videos) {
                mItems.add(SimpleMediaItem.from(video));
            }
        }

        @Override
        public int getType() {
            return mType;
        }

        @Override
        public List<MediaItem> getMediaItems() {
            return mItems;
        }

        @Override
        public String getTitle() {
            return "Row";
        }

        @Override
        public String getChannelId() {
            return null;
        }

        @Override
        public String getParams() {
            return null;
        }

        @Override
        public String getReloadPageKey() {
            return null;
        }

        @Override
        public String getNextPageKey() {
            return null;
        }

        @Override
        public String getChannelUrl() {
            return null;
        }

        @Override
        public boolean isEmpty() {
            return mItems.isEmpty();
        }

        @Override
        public int getTopic() {
            return MediaGroup.TOPIC_NONE;
        }

        @Override
        public boolean isChannelRow() {
            return false;
        }

        @Override
        public boolean isSearchTopicRow() {
            return false;
        }

        @Override
        public int getRowKind() {
            return ROW_KIND_NONE;
        }

        @Override
        public int getFilteredVideoCount() {
            return 0;
        }
    }
}
