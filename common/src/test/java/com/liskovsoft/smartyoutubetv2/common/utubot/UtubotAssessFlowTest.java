package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.os.Looper;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.prefs.GlobalPreferences;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SimpleMediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.misc.HiddenVideoResolver;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import io.reactivex.Observable;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * The assess hook: HiddenVideoResolver holds the emission until the verdicts are in, VideoGroup hides or marks by them
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotAssessFlowTest {
    private static final int WAIT_FOR_ASSESS_MS = 5000;
    private static final long MAIN_LOOPER_POLL_MS = 20;
    private final Context mContext = RuntimeEnvironment.getApplication();
    private final AtomicInteger mAssessCalls = new AtomicInteger();
    private volatile boolean mAssessFails;
    private TinyHttpServer mServer;
    private UtubotSettings mSettings;

    @Before
    public void setUp() throws Exception {
        GlobalPreferences.instance(mContext);
        mServer = new TinyHttpServer();
        mServer.on("/v1/assess", request -> {
            mAssessCalls.incrementAndGet();

            if (mAssessFails) {
                return new TinyHttpServer.Response(500, "{}");
            }

            return new TinyHttpServer.Response(200, "{\"results\":["
                    + "{\"video_id\":\"bad\",\"status\":\"ready\",\"action\":\"hide\",\"mark_label\":\"Clickbait\"},"
                    + "{\"video_id\":\"meh\",\"status\":\"ready\",\"action\":\"mark\",\"mark_label\":\"Inflated 12m≈2m\"},"
                    + "{\"video_id\":\"wait\",\"status\":\"pending\",\"action\":\"hide\"},"
                    + "{\"video_id\":\"good\",\"status\":\"ready\",\"action\":\"none\"}]}");
        });
        mSettings = UtubotSettings.instance(mContext);
        mSettings.setUrl("http://127.0.0.1:" + mServer.getPort());
        mSettings.setToken("utb_test");
        mSettings.setAssessEnabled(true);
        mSettings.setMarkOnly(false);
    }

    @After
    public void tearDown() {
        mServer.stop();
    }

    private List<MediaGroup> resolve(MediaGroup group) throws InterruptedException {
        List<MediaGroup> shown = new ArrayList<>();
        Observable<MediaGroup> resolved = HiddenVideoResolver.resolveGroup(mContext, Observable.just(group), createSection());
        CountDownLatch finished = new CountDownLatch(1);
        resolved.subscribe(shown::add, error -> finished.countDown(), finished::countDown);

        // Some managers of the resolver emit on the main looper: it has to run while waiting
        long deadline = System.currentTimeMillis() + WAIT_FOR_ASSESS_MS;

        while (!finished.await(MAIN_LOOPER_POLL_MS, TimeUnit.MILLISECONDS)) {
            ShadowLooper.idleMainLooper();
            assertTrue("The resolver did not finish", System.currentTimeMillis() < deadline);
        }

        return shown;
    }

    /**
     * The rows are shown from what the resolver emits (see BrowsePresenter): it has to be the main thread, not the io thread the answer
     * of the backend came on (adapters of the grids changed off the UI thread raced with the layout and left the section empty)
     */
    @Test
    public void theVerdictsComeOutOnTheMainThreadNotOnTheThreadOfTheAnswer() throws Exception {
        Observable<Boolean> resolved = UtubotManager.instance(mContext).resolve(Collections.singletonList(createRow(video("bad"), video("good"))), createSection());
        AtomicReference<Thread> emittedOn = new AtomicReference<>();
        CountDownLatch finished = new CountDownLatch(1);
        resolved.subscribe(done -> emittedOn.set(Thread.currentThread()), error -> finished.countDown(), finished::countDown);
        long deadline = System.currentTimeMillis() + WAIT_FOR_ASSESS_MS;

        while (!finished.await(MAIN_LOOPER_POLL_MS, TimeUnit.MILLISECONDS)) {
            ShadowLooper.idleMainLooper();
            assertTrue("The resolver did not finish", System.currentTimeMillis() < deadline);
        }

        assertSame(Looper.getMainLooper().getThread(), emittedOn.get());
    }

    @Test
    public void hidesAndMarksByTheVerdicts() throws Exception {
        MediaGroup row = createRow(video("bad"), video("meh"), video("wait"), video("good"));
        List<MediaGroup> shown = resolve(row);

        assertEquals(1, shown.size());
        assertEquals(1, mAssessCalls.get());
        VideoGroup group = VideoGroup.from(shown.get(0), createSection());
        assertEquals(3, group.getSize());
        assertEquals("meh", group.get(0).videoId);
        assertEquals("Inflated 12m≈2m", group.get(0).utubotMark);
        assertEquals("wait", group.get(1).videoId);
        assertNull(group.get(1).utubotMark);
        assertEquals("good", group.get(2).videoId);
        assertNull(group.get(2).utubotMark);
    }

    @Test
    public void markOnlyKeepsTheHiddenWithAMark() throws Exception {
        mSettings.setMarkOnly(true);
        VideoGroup group = VideoGroup.from(resolve(createRow(video("bad"), video("good"))).get(0), createSection());

        assertEquals(2, group.getSize());
        assertEquals("Clickbait", group.get(0).utubotMark);
    }

    @Test
    public void errorsShowEverythingUnfiltered() throws Exception {
        mAssessFails = true;
        VideoGroup group = VideoGroup.from(resolve(createRow(video("bad2"), video("good2"))).get(0), createSection());

        assertEquals(2, group.getSize());
        assertNull(group.get(0).utubotMark);
    }

    @Test
    public void disabledAssessMakesNoCall() throws Exception {
        mSettings.setAssessEnabled(false);
        int before = mAssessCalls.get();
        VideoGroup group = VideoGroup.from(resolve(createRow(video("bad3"))).get(0), createSection());

        assertEquals(before, mAssessCalls.get());
        assertEquals(1, group.getSize());
    }

    @Test
    public void cachedVerdictsAreNotAskedAgain() throws Exception {
        resolve(createRow(video("good")));
        int calls = mAssessCalls.get();
        resolve(createRow(video("good")));

        assertEquals(calls, mAssessCalls.get());
    }

    private static BrowseSection createSection() {
        return new BrowseSection(MediaGroup.TYPE_HOME, "Section", BrowseSection.TYPE_GRID, 0);
    }

    private static MediaGroup createRow(Video... videos) {
        return new TestMediaGroup(MediaGroup.TYPE_HOME, videos);
    }

    private static Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        video.title = "Video " + id;
        video.author = "Channel";
        video.secondTitle = "Channel • 5K views • 3 weeks ago";
        return video;
    }

    private static final class TestMediaGroup implements MediaGroup {
        private final int mType;
        private final String mChannelId;
        private final List<MediaItem> mItems = new ArrayList<>();

        TestMediaGroup(int type, Video... videos) {
            this(type, null, videos);
        }

        TestMediaGroup(int type, String channelId, Video... videos) {
            mType = type;
            mChannelId = channelId;

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
            return mChannelId;
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
