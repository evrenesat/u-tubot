package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * What the app keeps of the backend it talks to (prompts, summaries, verdicts, captions) is dropped when the backend changes under it:
 * another address or another token, or the prompt list itself being changed.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotConnectionCacheTest {
    private static final int WAIT_MS = 5000;
    private static final String PROMPT_LIST = "{\"default\":\"builtin/tldr\",\"sets\":[{\"id\":\"builtin\",\"name\":\"Built-in\","
            + "\"prompts\":[{\"id\":\"tldr\",\"key\":\"builtin/tldr\",\"label\":\"TL;DR\"}]}]}";
    private static final String READY_ID = "readyAAAAAA";
    private static final String SLOW_ID = "slowBBBBBBB";
    private static final String CAPTIONS_ID = "capsCCCCCCC";
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotSettings mSettings;
    private UtubotManager mManager;
    private final AtomicInteger mPromptFetches = new AtomicInteger();
    private final AtomicInteger mSummaryFetches = new AtomicInteger();
    private final CountDownLatch mSlowArrived = new CountDownLatch(1);
    private final CountDownLatch mSlowMayAnswer = new CountDownLatch(1);
    private volatile boolean mRefreshFails;

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/prompts", request -> {
            if (request.method.equals("GET") && request.path.equals("/v1/prompts")) {
                mPromptFetches.incrementAndGet();
                return new TinyHttpServer.Response(200, PROMPT_LIST);
            }

            if (mRefreshFails) {
                return new TinyHttpServer.Response(500, "{}");
            }

            return new TinyHttpServer.Response(200, "{\"id\":\"demo\",\"name\":\"Demo\",\"prompts\":[]}");
        });
        mServer.on("/v1/videos/" + READY_ID + "/summary", request -> {
            mSummaryFetches.incrementAndGet();
            return new TinyHttpServer.Response(200, "{\"video_id\":\"" + READY_ID + "\",\"status\":\"ready\",\"text\":\"- one\"}");
        });
        mServer.on("/v1/videos/" + SLOW_ID + "/summary", request -> {
            mSlowArrived.countDown();
            mSlowMayAnswer.await(WAIT_MS, TimeUnit.MILLISECONDS);
            return new TinyHttpServer.Response(200, "{\"video_id\":\"" + SLOW_ID + "\",\"status\":\"ready\",\"text\":\"- from the old backend\"}");
        });
        mServer.on("/v1/videos/" + CAPTIONS_ID + "/captions", request -> new TinyHttpServer.Response(200,
                "{\"status\":\"ready\",\"tracks\":[{\"lang\":\"en\",\"label\":\"English\",\"url\":\"/v1/videos/" + CAPTIONS_ID + "/captions/en.vtt\"}]}"));

        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mSettings = UtubotSettings.instance(mActivity);
        mSettings.setUrl(backend());
        mSettings.setToken("token");
        mManager = UtubotManager.instance(mActivity);
    }

    @After
    public void stop() {
        mSlowMayAnswer.countDown();
        mServer.stop();
        mSettings.setUrl("");
        mSettings.setToken("");
    }

    private String backend() {
        return "http://127.0.0.1:" + mServer.getPort();
    }

    private static Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        video.title = "Title";

        return video;
    }

    private static Verdict readyVerdict(String id) {
        Verdict verdict = new Verdict();
        verdict.videoId = id;
        verdict.status = "ready";

        return verdict;
    }

    private void loadPrompts() {
        mManager.promptsObserve(false).blockingFirst();
    }

    /**
     * The prompt list the manager shows for the next request: from its memory or fetched again
     */
    private boolean promptsAreFetchedAgain() {
        int before = mPromptFetches.get();
        loadPrompts();

        return mPromptFetches.get() > before;
    }

    private void fillEveryCache() throws InterruptedException {
        loadPrompts();
        mManager.setSessionPrompt("builtin/tldr");
        mManager.putVerdict(readyVerdict("v1"));
        mManager.summaryObserve(video(READY_ID), "panel").blockingFirst();
        mManager.prefetchCaptions(CAPTIONS_ID);

        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (mManager.getCachedCaptions(CAPTIONS_ID) == null && System.currentTimeMillis() < deadline) {
            Thread.sleep(20);
        }

        assertNotNull(mManager.getVerdict("v1"));
        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNotNull(mManager.getCachedCaptions(CAPTIONS_ID));
        assertEquals("builtin/tldr", mManager.getSessionPrompt());
    }

    private void assertEveryCacheIsEmpty() {
        assertNull(mManager.getVerdict("v1"));
        assertNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNull(mManager.getCachedCaptions(CAPTIONS_ID));
        assertNull(mManager.getSessionPrompt());
        assertTrue(promptsAreFetchedAgain());
    }

    @Test
    public void thePromptListIsKeptBetweenRequests() {
        loadPrompts();

        assertFalse(promptsAreFetchedAgain());
        assertEquals(1, mPromptFetches.get());

        mManager.promptsObserve(true).blockingFirst();

        assertEquals("a forced reload still goes to the backend", 2, mPromptFetches.get());
    }

    @Test
    public void settingTheDefaultPromptDropsTheKeptList() {
        loadPrompts();

        mManager.setDefaultPromptObserve("builtin/tldr").blockingFirst();

        assertTrue(promptsAreFetchedAgain());
    }

    @Test
    public void importingAPromptSetDropsTheKeptList() {
        loadPrompts();

        mManager.importPromptsObserve("https://sets.example.com/p.json").blockingFirst();

        assertTrue(promptsAreFetchedAgain());
    }

    @Test
    public void refreshingThePromptSetsDropsTheKeptList() {
        loadPrompts();

        mManager.refreshPromptsObserve().blockingFirst();

        assertTrue(promptsAreFetchedAgain());
    }

    @Test
    public void theSetupsPendingPromptSetsDropTheKeptListToo() throws Exception {
        loadPrompts();
        StoredSettings.prefsOf(mSettings).edit().putString("pending_prompt_sets", "https://sets.example.com/p.json").commit();

        UtubotSetupFlow.importPendingPromptSets(mActivity);

        // The import runs on an io thread: the list is fetched again once it is through
        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (!promptsAreFetchedAgain() && System.currentTimeMillis() < deadline) {
            Thread.sleep(20);
        }

        assertEquals("the kept list was never dropped", 2, mPromptFetches.get());
    }

    @Test
    public void aFailedPromptChangeDropsTheKeptListToo() {
        loadPrompts();
        mRefreshFails = true;

        try {
            mManager.refreshPromptsObserve().blockingFirst();
            fail("the refresh should have failed");
        } catch (RuntimeException expected) {
            // the backend answered 500: it may have changed the list before that
        }

        assertTrue(promptsAreFetchedAgain());
    }

    @Test
    public void aNewBackendAddressDropsEverythingKeptOfTheOldOne() throws Exception {
        fillEveryCache();

        mSettings.setUrl("http://127.0.0.1:1");

        assertNull(mManager.getVerdict("v1"));
        assertNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNull(mManager.getCachedCaptions(CAPTIONS_ID));
        assertNull(mManager.getSessionPrompt());
    }

    @Test
    public void importingASetupForAnotherBackendDropsEverythingKept() throws Exception {
        fillEveryCache();

        mSettings.applySetup(UtubotSetup.parse("{\"utubot_setup\":1,\"backend_url\":\"https://other.example.com\"}"));

        assertNull(mManager.getVerdict("v1"));
        assertNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNull(mManager.getCachedCaptions(CAPTIONS_ID));
        assertNull(mManager.getSessionPrompt());
    }

    @Test
    public void typingAnotherBackendDropsEverythingKept() throws Exception {
        fillEveryCache();

        mSettings.setUrlManually("https://other.example.com");

        assertNull(mManager.getVerdict("v1"));
        assertNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNull(mManager.getCachedCaptions(CAPTIONS_ID));
    }

    @Test
    public void clearingTheBackendDropsEverythingKept() throws Exception {
        fillEveryCache();

        mSettings.setUrlManually("");

        assertNull(mManager.getVerdict("v1"));
        assertNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNull(mManager.getCachedCaptions(CAPTIONS_ID));
    }

    @Test
    public void aNewTokenDropsEverythingKept() throws Exception {
        fillEveryCache();

        // What the pairing stores
        mSettings.setToken("another-token");

        assertEveryCacheIsEmpty();
    }

    @Test
    public void theSameAddressAndTokenKeepWhatWasLoaded() throws Exception {
        fillEveryCache();

        mSettings.setUrl(backend() + " ");
        mSettings.setToken("token");
        mSettings.applySetup(UtubotSetup.parse("{\"utubot_setup\":1,\"backend_url\":\"" + backend() + "\"}"));

        assertNotNull(mManager.getVerdict("v1"));
        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        assertNotNull(mManager.getCachedCaptions(CAPTIONS_ID));
        assertEquals("builtin/tldr", mManager.getSessionPrompt());
        assertFalse(promptsAreFetchedAgain());
    }

    @Test
    public void aSummaryThatArrivesAfterTheSwitchBelongsToTheOldBackendAndIsNotKept() throws Exception {
        CountDownLatch answered = new CountDownLatch(1);
        mManager.summaryObserve(video(SLOW_ID), "panel").subscribe(summary -> answered.countDown(), error -> answered.countDown());
        assertTrue(mSlowArrived.await(WAIT_MS, TimeUnit.MILLISECONDS));

        mSettings.setToken("another-token");
        mSlowMayAnswer.countDown();

        assertTrue(answered.await(WAIT_MS, TimeUnit.MILLISECONDS));
        assertNull(mManager.getCachedSummary(SLOW_ID, "panel"));
    }

    @Test
    public void aSummaryOfTheCurrentBackendIsKept() {
        Summary summary = mManager.summaryObserve(video(READY_ID), "panel").blockingFirst();

        assertTrue(summary.isReady());
        assertNotNull(mManager.getCachedSummary(READY_ID, "panel"));
        mManager.summaryObserve(video(READY_ID), "panel").blockingFirst();
        assertEquals(1, mSummaryFetches.get());
    }
}
