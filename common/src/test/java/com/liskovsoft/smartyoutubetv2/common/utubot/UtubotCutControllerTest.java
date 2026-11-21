package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The engine lifecycle of the cut controller: a release does not end the follower of the video that stays (the HQ format change, the
 * fixer's restart and the home round trip load the same video with no onNewVideo), and a cut that waits for the length survives a reload.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutControllerTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String REQUEST = "cut1";

    private final FakeScheduler mScheduler = new FakeScheduler();
    private final Queue<Object> mCutsAnswers = new ConcurrentLinkedQueue<>();
    private final Queue<Object> mRequestAnswers = new ConcurrentLinkedQueue<>();
    private final List<String> mFetchedRequests = new ArrayList<>();
    private Context mContext;
    private TestCutController mController;

    @Before
    public void setUp() throws Exception {
        mContext = RuntimeEnvironment.getApplication();
        UtubotSettings.instance(mContext).setUrl("http://127.0.0.1:9");

        UtubotCutFollower follower = new UtubotCutFollower(mScheduler, new UtubotCutFollower.Fetcher() {
            @Override
            public void fetchCuts(String videoId, UtubotCutFollower.CutsCallback callback) {
                Object answer = mCutsAnswers.poll();

                if (answer instanceof Throwable) {
                    callback.onError((Throwable) answer);
                } else {
                    callback.onResult((CutList) answer);
                }
            }

            @Override
            public void fetchRequest(String requestId, int waitMs, UtubotCutFollower.RequestCallback callback) {
                mFetchedRequests.add(requestId);
                Object answer = mRequestAnswers.poll();

                if (answer instanceof Throwable) {
                    callback.onError((Throwable) answer);
                } else {
                    callback.onResult((CutRequest) answer);
                }
            }
        }, mScheduler::now);

        Field followerField = UtubotManager.class.getDeclaredField("mCutsFollower");
        followerField.setAccessible(true);
        followerField.set(UtubotManager.instance(mContext), follower);

        mController = new TestCutController();
        mController.attach(mContext);
    }

    @After
    public void tearDown() {
        UtubotCutSeekBar.setCut(null, null);
    }

    @Test
    public void aRequestAfterAnEngineRelease_isFollowed() {
        mCutsAnswers.add(cutsEmpty());
        mController.onNewVideo(video(VIDEO));
        mController.onEngineReleased();

        UtubotManager.instance(mContext).cutRequested(VIDEO, REQUEST, UtubotModels.CutState.BUILDING);
        mRequestAnswers.add(request(REQUEST, UtubotModels.CutState.READY));

        mScheduler.advance(1_000);

        assertEquals(Collections.singletonList(REQUEST), mFetchedRequests);
    }

    @Test
    public void aBuildingRequestSurvivesAnEngineRelease() {
        mCutsAnswers.add(cutsPreset(REQUEST, UtubotModels.CutState.BUILDING));

        mController.onNewVideo(video(VIDEO));
        mController.onEngineReleased();

        mRequestAnswers.add(request(REQUEST, UtubotModels.CutState.READY));
        mScheduler.advance(1_000);

        assertEquals(Collections.singletonList(REQUEST), mFetchedRequests);
    }

    @Test
    public void aPendingCut_isReArmedOnASameVideoReload() {
        mCutsAnswers.add(cutsEmpty());
        setPendingCut(cut(VIDEO));

        mController.onNewVideo(video(VIDEO));

        assertNotNull(getPendingCut());
    }

    @Test
    public void aPendingCutOfAnotherVideo_isDropped() {
        mCutsAnswers.add(cutsEmpty());
        setPendingCut(cut("othervideo00"));

        mController.onNewVideo(video(VIDEO));

        assertNull(getPendingCut());
    }

    @Test
    public void aReadyPendingCutSurvivesAnEngineRelease() {
        setPendingCut(cut(VIDEO));

        mController.onEngineReleased();

        assertNotNull(getPendingCut());
    }

    @Test
    public void errorsOfARequestAfterAnEngineRelease_areRetried() {
        mCutsAnswers.add(cutsEmpty());
        mController.onNewVideo(video(VIDEO));
        mController.onEngineReleased();

        UtubotManager.instance(mContext).cutRequested(VIDEO, REQUEST, UtubotModels.CutState.BUILDING);
        mRequestAnswers.add(new IOException("down"));
        mRequestAnswers.add(request(REQUEST, UtubotModels.CutState.READY));

        mScheduler.advance(UtubotCutFollower.MAX_FOLLOW_MS);

        assertTrue(mFetchedRequests.size() >= 2);
        assertEquals(REQUEST, mFetchedRequests.get(mFetchedRequests.size() - 1));
    }

    @Test
    public void aKeptPart_isOneLineWithItsTimesAndLabel() {
        CutPart part = new CutPart();
        part.label = "The demo";
        part.startMs = 130_000;
        part.endMs = 185_000;

        assertEquals("2:10 - 3:05  The demo", UtubotCutController.formatPart(part));
    }

    @Test
    public void aKeptPartWithoutALabel_isJustItsTimes() {
        CutPart part = new CutPart();
        part.startMs = 65_000;
        part.endMs = 122_000;

        assertEquals("1:05 - 2:02", UtubotCutController.formatPart(part));
        assertEquals("", UtubotCutController.formatPart(null));
    }

    private static final class TestCutController extends UtubotCutController {
        void attach(Context context) {
            setAltContext(context);
        }
    }

    private void setPendingCut(Cut cut) {
        try {
            Field field = UtubotCutController.class.getDeclaredField("mPendingCut");
            field.setAccessible(true);
            field.set(mController, cut);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    private Cut getPendingCut() {
        try {
            Field field = UtubotCutController.class.getDeclaredField("mPendingCut");
            field.setAccessible(true);
            return (Cut) field.get(mController);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    private Video video(String id) {
        Video video = new Video();
        video.videoId = id;
        return video;
    }

    private Cut cut(String videoId) {
        Cut cut = new Cut();
        cut.videoId = videoId;
        return cut;
    }

    private CutList cutsEmpty() {
        CutList cuts = new CutList();
        cuts.configured = true;
        cuts.presets = Collections.emptyList();
        return cuts;
    }

    private CutList cutsPreset(String requestId, String state) {
        CutList cuts = cutsEmpty();
        CutPreset preset = new CutPreset();
        preset.id = "no-filler";
        preset.label = "No filler";
        preset.state = state;
        preset.requestId = requestId;
        cuts.presets = Collections.singletonList(preset);
        return cuts;
    }

    private CutRequest request(String id, String state) {
        CutRequest request = new CutRequest();
        request.id = id;
        request.state = state;

        if (UtubotModels.CutState.READY.equals(state)) {
            request.cut = cut(VIDEO);
        }

        return request;
    }
}
