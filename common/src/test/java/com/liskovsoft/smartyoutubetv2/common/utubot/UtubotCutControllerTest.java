package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutSelection;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowToast;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.function.Consumer;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
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
        resetDialogBackup();
    }

    @After
    public void tearDown() {
        UtubotCutSeekBar.setCut(null, null);
        UtubotSettings.instance(mContext).setApplyReadyCutsEnabled(false);
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

    /**
     * A cut that waited for another video is dropped at the open: it never says the lengths differ for the video that plays
     */
    @Test
    public void aPendingCutOfAnotherVideo_doesNotClaimADifferentLength() {
        Cut cut = cut("othervideo00");
        cut.label = "No filler";
        cut.durationMs = 200_000;
        setPendingCut(cut);
        mController.open(video(VIDEO), 240_000);

        mController.onNewVideo(video(VIDEO));
        mController.onVideoLoaded(video(VIDEO));

        assertNull(getPendingCut());
        assertFalse(mController.isApplied(cut));
        assertNull(ShadowToast.getTextOfLatestToast());
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


    /**
     * The picker of a video that isn't playing yet (a card of a list) has no player length to compare: toggle answers false and
     * says nothing. Before, it claimed the cut was built for a different length.
     */
    @Test
    public void aPickerWithNoPlayer_doesNotClaimADifferentLength() {
        Cut cut = cut(VIDEO);
        cut.durationMs = 240_000;

        assertFalse(mController.toggle(cut));
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * The picker was built for another card: the player is another video, so no length claim either
     */
    @Test
    public void aPickerOfAnotherVideo_doesNotClaimADifferentLength() {
        mController.open(video("othervideo00"), 240_000);

        assertFalse(mController.toggle(cut(VIDEO)));
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * The length is not known yet: the cut waits for it, with no message
     */
    @Test
    public void aCutPickedBeforeTheLengthIsKnown_waitsWithoutAMessage() {
        mController.open(video(VIDEO), 0);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;

        assertTrue(mController.toggle(cut));
        assertNotNull(getPendingCut());
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * A real mismatch of the video that plays is the only case the different-length message belongs to
     */
    @Test
    public void aCutOfAnotherLength_forTheVideoThatPlays_saysSo() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 200_000;

        assertTrue(mController.toggle(cut));
        assertEquals(mContext.getString(R.string.utubot_cut_other_length), ShadowToast.getTextOfLatestToast());
    }

    /**
     * The follower sends the ready list through {@code onCutsReady}, and "Apply ready cuts automatically" does not turn a ready
     * cut that nobody chose into an applied one: every cut is offered with its own Apply.
     */
    @Test
    public void aReadyCutFromTheFollower_isOfferedEvenWithTheSettingOn() {
        UtubotSettings.instance(mContext).setApplyReadyCutsEnabled(true);
        mController.open(video(VIDEO), 240_000);
        Cut cut = cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000);

        mController.onCutsReady(VIDEO, Collections.singletonList(cut));

        assertEquals(155, readyOfferId());
        assertFalse(mController.isApplied(cut));
        mController.onFinish();
    }

    /**
     * A cut picked in the picker of a list is carried to the normal playback path: the video open arms it, and the length it gets
     * later applies it
     */
    @Test
    public void aCutPickedBeforeTheVideoOpens_isAppliedAsTheVideoOpens() {
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;
        mCutsAnswers.add(cutsEmpty());
        mController.applyOnOpen(cut);
        mController.open(video(VIDEO), 240_000);

        mController.onNewVideo(video(VIDEO));
        assertNotNull(getPendingCut()); // waits for the video's length, like a cut that came ready with it

        mController.onVideoLoaded(video(VIDEO));

        assertTrue(mController.isApplied(cut));
        assertNull(getPendingCut());
    }

    /**
     * The cuts answer of the open can still carry the preset used last (or the old choice) because the choice write of the picker
     * races it: it must not replace the cut the viewer just picked for this video.
     */
    @Test
    public void aStaleLastCut_doesNotReplaceTheCutPickedBeforeTheOpen() {
        Cut picked = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);
        Cut staleLast = cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000);
        mCutsAnswers.add(cutsEmpty());
        mController.applyOnOpen(picked);
        mController.open(video(VIDEO), 240_000);

        mController.onNewVideo(video(VIDEO));
        mController.onCutChosen(VIDEO, staleLast);
        mController.onVideoLoaded(video(VIDEO));

        assertTrue(mController.isApplied(picked));
        assertFalse(mController.isApplied(staleLast));
        assertNull(getPendingCut());
        mController.onFinish();
    }

    /**
     * Turning the cut off writes the choice asynchronously too: a cuts answer built before the off lands must not bring the old
     * chosen/last cut back when the video reopens.
     */
    @Test
    public void aStaleCut_doesNotOverrideTheOffJustChosen() {
        mController.open(video(VIDEO), 240_000);
        Cut old = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);
        assertTrue(mController.toggle(old));
        assertTrue(mController.toggle(old)); // the applied cut again: off, and the off write goes out

        mController.onFinish();
        mController.open(video(VIDEO), 240_000);
        mCutsAnswers.add(cutsEmpty());
        mController.onNewVideo(video(VIDEO));

        Cut staleLast = cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000);
        mController.onCutChosen(VIDEO, staleLast);
        mController.onVideoLoaded(video(VIDEO));

        assertFalse(mController.isApplied(staleLast));
        assertNull(getPendingCut());
        mController.onFinish();
    }

    /**
     * A stale ready list must not offer cuts the viewer just turned off, while the off write is still in flight.
     */
    @Test
    public void aStaleReadyList_doesNotOfferCutsAfterTheOff() {
        mController.open(video(VIDEO), 240_000);
        Cut old = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);
        assertTrue(mController.toggle(old));
        assertTrue(mController.toggle(old));

        mController.onFinish();
        mController.open(video(VIDEO), 240_000);
        mCutsAnswers.add(cutsEmpty());
        mController.onNewVideo(video(VIDEO));

        mController.onCutsReady(VIDEO, Collections.singletonList(
                cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000)));

        assertFalse(readyOfferId() == 155);
        mController.onFinish();
    }

    /**
     * A request followed from the list can finish after the viewer picked another cut here: it must neither replace that pick nor
     * offer itself over it.
     */
    @Test
    public void aReadyRequest_doesNotReplaceTheCutPickedAfterItStarted() {
        mController.open(video(VIDEO), 240_000);
        Cut picked = cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000);
        Cut olderRequest = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);
        assertTrue(mController.toggle(picked));

        mController.onCutReady(VIDEO, olderRequest, false);

        assertTrue(mController.isApplied(picked));
        assertFalse(mController.isApplied(olderRequest));
        assertFalse(readyOfferId() == 155);
        mController.onFinish();
    }

    /**
     * The player's picker applies a ready cut and takes it off again on the same row
     */
    @Test
    public void aReadyCut_pickedInThePlayer_appliesAndTurnsOff() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;

        assertTrue(mController.toggle(cut));
        assertTrue(mController.isApplied(cut));

        assertTrue(mController.toggle(cut));
        assertFalse(mController.isApplied(cut));
    }

    /**
     * A finished playback leaves no applied cut: a picker of the same video from a list carries it to the reopened video instead
     * of turning a cut off that isn't playing
     */
    @Test
    public void afterAFinish_aListPickerOfThatVideo_doesNotTurnOff() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;
        assertTrue(mController.toggle(cut));

        mController.onFinish();
        assertFalse(mController.isApplied(cut));

        mController.close();
        assertFalse(mController.toggle(cut));
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * A view whose engine was released is not the video that plays even while the last video is still reachable: a list picker of that
     * video carries the cut to the reopened video instead of turning off a cut that is not running
     */
    @Test
    public void afterARelease_aListPickerOfThatVideo_doesNotTurnOff() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;
        assertTrue(mController.toggle(cut));

        mController.releasePlayer();

        assertFalse(mController.toggle(cut));
        assertTrue(mController.isApplied(cut)); // not turned off: the next open carries it
        assertNull(getPendingCut());
        assertNull(ShadowToast.getTextOfLatestToast());
        mController.onFinish();
    }

    /**
     * A released view still answers the old length: a picker of that video must not queue the cut or claim a length for a playback that
     * is gone
     */
    @Test
    public void afterARelease_aListPickerOfThatVideo_queuesNothing() {
        mController.open(video(VIDEO), 240_000);
        mController.releasePlayer();
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 200_000;

        assertFalse(mController.toggle(cut));
        assertNull(getPendingCut());
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * A ready cut of the video that plays is offered with a one-press Apply, and that press applies it
     */
    @Test
    public void aReadyCut_isOfferedAndAppliedOnOnePress() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;

        mController.onCutReady(VIDEO, cut, false);

        assertEquals(155, readyOfferId()); // READY_DIALOG_ID
        OptionItem apply = readyApplyButton();
        assertEquals(mContext.getString(R.string.utubot_cut_apply), apply.getTitle());

        apply.onSelect(true);

        assertTrue(mController.isApplied(cut));
        assertNull(getPendingCut());
        mController.onFinish();
    }

    /**
     * The Apply offer lives a moment: when the playback changes inside it, its press must not apply the old video's cut to the new video
     */
    @Test
    public void aReadyOfferPressedAfterAPlaybackChange_isNotApplied() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;
        mController.onCutReady(VIDEO, cut, false);
        OptionItem apply = readyApplyButton();

        mController.open(video("othervideo00"), 240_000);

        apply.onSelect(true);

        assertFalse(mController.isApplied(cut));
        assertNull(getPendingCut());
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * A pending cut is only tried on the video it was built for: a playback change with equal lengths must not apply it to another video
     */
    @Test
    public void aPendingCutOfAnotherVideo_isNotTriedOnThisVideo() {
        mController.open(video("othervideo00"), 240_000);
        Cut cut = cut(VIDEO);
        cut.label = "No filler";
        cut.durationMs = 240_000;
        setPendingCut(cut);

        mController.onVideoLoaded(video("othervideo00"));

        assertNull(getPendingCut());
        assertFalse(mController.isApplied(cut));
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * The queued cut is only for the video it was built for: another video drops it
     */
    @Test
    public void aCutPickedForAnotherVideo_isDroppedOnOpen() {
        mCutsAnswers.add(cutsEmpty());
        mController.applyOnOpen(cut("othervideo00"));

        mController.onNewVideo(video(VIDEO));

        assertNull(getPendingCut());
    }

    /**
     * The cut the viewer chose (or the preset used last) is what the video opens with, even when other cuts are ready and
     * whatever "apply ready cuts automatically" says.
     */
    @Test
    public void aChosenCut_isAppliedWhenTheVideoOpens() {
        mController.open(video(VIDEO), 240_000);
        Cut cut = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);

        mController.onCutChosen(VIDEO, cut);

        assertTrue(mController.isApplied(cut));
        assertNull(getPendingCut());
        mController.onFinish();
    }

    /**
     * The cuts answer can land before the player and its engine exist (the open runs before startView): the chosen cut is queued
     * rather than dropped, and applies once the engine is initialized and the length is known.
     */
    @Test
    public void aChosenCutArrivingBeforeTheEngine_isAppliedOnceItInitializes() {
        CutList cuts = cutsWithSelection(
                new String[]{"cut-no-filler", "No filler", "cut-demo", "Only the demo"}, "cut-demo",
                UtubotModels.CutState.READY);
        Cut chosen = cuts.presets.get(1).cut;
        mCutsAnswers.add(cuts);

        mController.onNewVideo(video(VIDEO)); // before startView: no player at all
        assertNotNull(getPendingCut());

        mController.open(video(VIDEO), 240_000);
        mController.onEngineInitialized();

        assertTrue(mController.isApplied(chosen));
        assertNull(getPendingCut());
        mController.onFinish();
    }

    /**
     * The ready list can land before the engine exists too: the offer waits for the player instead of being lost, and the video
     * still does not take a cut by itself.
     */
    @Test
    public void readyCutsArrivingBeforeTheEngine_areOfferedOnceItInitializes() {
        CutList cuts = cutsWithSelection(
                new String[]{"cut-no-filler", "No filler", "cut-demo", "Only the demo"}, null,
                UtubotModels.CutState.NONE);
        mCutsAnswers.add(cuts);

        mController.onNewVideo(video(VIDEO)); // before startView: no player at all
        assertFalse(readyOfferId() == 155);

        mController.open(video(VIDEO), 240_000);
        mController.onEngineInitialized();

        assertEquals(155, readyOfferId());
        assertEquals(2, readyApplyButtons().size());
        assertFalse(mController.isApplied(cuts.presets.get(0).cut));
        assertFalse(mController.isApplied(cuts.presets.get(1).cut));
        mController.onFinish();
    }

    /**
     * A chosen request that is still building when the video opens is applied when it becomes ready, from the current position,
     * rather than offered as an ordinary ready cut.
     */
    @Test
    public void aChosenRequestThatBecomesReadyWhilePlaying_isApplied() {
        mController.open(video(VIDEO), 240_000);

        CutList cuts = cutsWithSelection(
                new String[]{"cut-no-filler", "No filler", "cut-demo", "Only the demo"}, null,
                UtubotModels.CutState.NONE);
        cuts.selection = new CutSelection();
        cuts.selection.source = "chosen";
        cuts.selection.requestId = REQUEST;
        cuts.selection.state = UtubotModels.CutState.BUILDING;
        mCutsAnswers.add(cuts);

        mController.onNewVideo(video(VIDEO));

        CutRequest request = request(REQUEST, UtubotModels.CutState.READY);
        request.cut = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);
        mRequestAnswers.add(request);
        mScheduler.advance(1_000);

        assertTrue(mController.isApplied(request.cut));
        assertNull(getPendingCut());
        assertFalse(readyOfferId() == 155);
        mController.onFinish();
    }

    /**
     * No choice for this video and no ready cut for the last preset: every ready cut is offered, none applied by itself.
     */
    @Test
    public void severalReadyCuts_areOfferedAndNoneApplied() {
        mController.open(video(VIDEO), 240_000);
        Cut first = cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000);
        Cut second = cutWithPreset(VIDEO, "cut-demo", "Only the demo", 240_000);

        mController.onCutsReady(VIDEO, Arrays.asList(first, second));

        assertEquals(155, readyOfferId()); // READY_DIALOG_ID
        List<OptionItem> options = readyApplyButtons();
        assertEquals(2, options.size());
        assertEquals("No filler \u00b7 4:00", options.get(0).getTitle());
        assertEquals("Only the demo \u00b7 4:00", options.get(1).getTitle());
        assertFalse(mController.isApplied(first));
        assertFalse(mController.isApplied(second));

        options.get(1).onSelect(true);

        assertTrue(mController.isApplied(second));
        assertFalse(mController.isApplied(first));
        mController.onFinish();
    }

    /**
     * A cut that is already ready in the list but is not the viewer's choice is never applied silently, even with the setting on.
     */
    @Test
    public void anUnchosenReadyCut_isNotAppliedEvenWithTheAutoSetting() {
        UtubotSettings.instance(mContext).setApplyReadyCutsEnabled(true);
        mController.open(video(VIDEO), 240_000);
        Cut cut = cutWithPreset(VIDEO, "cut-no-filler", "No filler", 240_000);

        mController.onCutsReady(VIDEO, Collections.singletonList(cut));

        assertEquals(155, readyOfferId());
        assertFalse(mController.isApplied(cut));
        mController.onFinish();
    }

    /**
     * The player's cut button names the cut that is on, with its real length, and goes back to the menu label when it is off.
     */
    @Test
    public void thePlayerButtonNamesTheAppliedCut() {
        mController.open(video(VIDEO), 2_480_000);
        Cut cut = cutWithPreset(VIDEO, "cut-half", "Half", 2_480_000);
        cut.keptMs = 2_480_000;

        mController.onCutChosen(VIDEO, cut);
        assertTrue(mController.isApplied(cut));
        assertEquals(mContext.getString(R.string.utubot_cut_player_label, "Half", "41:20"), mController.getButtonLabel());

        assertTrue(mController.toggle(cut));
        assertFalse(mController.isApplied(cut));
        assertEquals(mContext.getString(R.string.utubot_cut_menu), mController.getButtonLabel());
        mController.onFinish();
    }

    /**
     * The last drop of a cut that ends before the video end is the end of the cut: the player says so and offers the rest, instead of
     * reporting it as another middle skip
     */
    @Test
    public void theTrailingDrop_isTheEndOfTheCut() {
        Cut cut = cut(VIDEO);
        cut.durationMs = 240_000;
        cut.skipRangesMs = Arrays.asList(new long[]{60_000, 108_000}, new long[]{204_000, 240_000});

        assertTrue(UtubotCutController.isCutEnd(cut, 205_000));
        assertFalse(UtubotCutController.isCutEnd(cut, 107_000));
        assertFalse(UtubotCutController.isCutEnd(cut, 203_000));

        Cut keptToTheEnd = cut(VIDEO);
        keptToTheEnd.durationMs = 240_000;
        keptToTheEnd.skipRangesMs = Arrays.asList(new long[]{60_000, 108_000});
        assertFalse(UtubotCutController.isCutEnd(keptToTheEnd, 205_000));
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

    @Test
    public void aReadyPresetShowsItsRealLengthNextToTheLabel() {
        assertEquals("Highlights in 5 min \u00b7 5:02", UtubotCutController.presetTitle("Highlights in 5 min", 302_000));
        assertEquals("Only the demo \u00b7 1:02:03", UtubotCutController.presetTitle("Only the demo", 3_723_000));
        assertEquals("Highlights in 5 min", UtubotCutController.presetTitle("Highlights in 5 min", UtubotModels.UNKNOWN));
    }

    private static final class TestCutController extends UtubotCutController {
        private Video mVideo;
        private PlaybackView mPlayer;
        private long mDurationMs;
        private String mButtonLabel;

        void attach(Context context) {
            setAltContext(context);
        }

        void open(Video video, long durationMs) {
            mVideo = video;
            mPlayer = player(durationMs, true, label -> mButtonLabel = label);
            mDurationMs = durationMs;
        }

        String getButtonLabel() {
            return mButtonLabel;
        }

        void releasePlayer() {
            // Like PlaybackFragment.releasePlayer: the view stays as the presenter's weak reference, its engine is gone (and the stale
            // length it reports must not count either)
            mPlayer = player(mDurationMs, false);
        }

        void close() {
            mVideo = null;
            mPlayer = null;
        }

        @Override
        public Video getVideo() {
            return mVideo;
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }
    }

    /**
     * A player of a known length whose engine stands initialized: the defaults answer every other call
     */
    private static PlaybackView player(long durationMs) {
        return player(durationMs, true);
    }

    private static PlaybackView player(long durationMs, boolean engineInitialized) {
        return player(durationMs, engineInitialized, label -> { });
    }

    private static PlaybackView player(long durationMs, boolean engineInitialized, Consumer<String> onButtonLabel) {
        return (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                (proxy, method, args) -> {
                    if ("getDurationMs".equals(method.getName())) {
                        return durationMs;
                    }

                    if ("isEngineInitialized".equals(method.getName())) {
                        return engineInitialized;
                    }

                    if ("setButtonLabel".equals(method.getName())) {
                        onButtonLabel.accept(String.valueOf(args[1]));
                        return null;
                    }

                    Class<?> type = method.getReturnType();

                    if (type == boolean.class) {
                        return false;
                    } else if (type == int.class) {
                        return 0;
                    } else if (type == long.class) {
                        return 0L;
                    } else if (type == float.class) {
                        return 0f;
                    }

                    return null;
                });
    }

    private int readyOfferId() {
        try {
            Field field = AppDialogPresenter.class.getDeclaredField("mBackupId");
            field.setAccessible(true);
            return (int) field.get(AppDialogPresenter.instance(mContext));
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    /**
     * The dialog presenter is a singleton that outlives one test: a leftover offer's id would count as this test's
     */
    private void resetDialogBackup() {
        try {
            AppDialogPresenter dialog = AppDialogPresenter.instance(mContext);

            Field id = AppDialogPresenter.class.getDeclaredField("mBackupId");
            id.setAccessible(true);
            id.set(dialog, 0);

            Field categories = AppDialogPresenter.class.getDeclaredField("mBackupCategories");
            categories.setAccessible(true);
            categories.set(dialog, null);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    @SuppressWarnings("unchecked")
    private OptionItem readyApplyButton() {
        try {
            Field field = AppDialogPresenter.class.getDeclaredField("mBackupCategories");
            field.setAccessible(true);
            List<OptionCategory> categories = (List<OptionCategory>) field.get(AppDialogPresenter.instance(mContext));

            return categories.get(0).options.get(0);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
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

    private Cut cutWithPreset(String videoId, String presetId, String label, long durationMs) {
        Cut cut = cut(videoId);
        cut.presetId = presetId;
        cut.label = label;
        cut.durationMs = durationMs;
        cut.keptMs = durationMs;
        return cut;
    }

    @SuppressWarnings("unchecked")
    private List<OptionItem> readyApplyButtons() {
        try {
            Field field = AppDialogPresenter.class.getDeclaredField("mBackupCategories");
            field.setAccessible(true);
            List<OptionCategory> categories = (List<OptionCategory>) field.get(AppDialogPresenter.instance(mContext));
            List<OptionItem> options = new ArrayList<>();

            for (OptionCategory category : categories) {
                options.addAll(category.options);
            }

            return options;
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

    private CutList cutsWithSelection(String[] presets, String chosenPresetId, String chosenState) {
        CutList cuts = cutsEmpty();
        List<CutPreset> list = new ArrayList<>();

        for (int i = 0; i < presets.length; i += 2) {
            CutPreset preset = new CutPreset();
            preset.id = presets[i];
            preset.label = presets[i + 1];
            preset.state = UtubotModels.CutState.READY;
            preset.cut = cutWithPreset(VIDEO, preset.id, preset.label, 240_000);
            list.add(preset);
        }

        cuts.presets = list;

        if (chosenPresetId != null) {
            CutSelection selection = new CutSelection();
            selection.source = "chosen";
            selection.presetId = chosenPresetId;
            selection.state = chosenState;

            for (CutPreset preset : list) {
                if (preset.id.equals(chosenPresetId)) {
                    selection.cut = preset.cut;
                }
            }

            cuts.selection = selection;
        }

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
