package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.data.MediaItemMetadata;
import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.BasePlayerController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers.SponsorBlockController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;
import com.liskovsoft.sharedutils.rx.RxHelper;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import io.reactivex.disposables.Disposable;

/**
 * Plays the director's cut of the video that plays: the cut's dropped ranges are skipped with the sponsor-skip machinery, one jump past
 * every sponsor segment the destination touches, the skips are dimmed on the seek bar and every skip says "Skipped" with a Back that
 * undoes it for a moment. A seek of the user wins and plays; a cut built for a video of another length is not applied.
 */
public class UtubotCutController extends BasePlayerController implements UtubotCutFollower.Listener {
    private static final String TAG = UtubotCutController.class.getSimpleName();
    private static final long POLL_INTERVAL_MS = 1_000;
    private static final long TOAST_BACK_MS = 5_000;
    private static final long READY_OFFER_MS = 8_000;
    private static final int CUT_DIALOG_ID = 154;
    private static final int READY_DIALOG_ID = 155;
    /** The colour of the skipped parts on the seek bar: dimmed, clearly not a sponsor block category */
    private static final int SKIP_COLOR = 0x99607080;
    @Nullable
    private Video mVideo;
    @Nullable
    private Cut mOpenCut;
    @Nullable
    private Cut mPendingCut;
    @Nullable
    private List<Cut> mReadyCuts;
    /**
     * The explicit choices this TV made itself, per video: their writes reach the backend asynchronously, so a cuts answer that
     * still carries the old choice must not undo them. A pick lasts until the backend confirms it or the video is left; an off
     * lasts until the viewer picks a cut here again.
     */
    private final Map<String, String> mLocalPicks = new HashMap<>();
    private final Set<String> mLocalOffs = new HashSet<>();
    @Nullable
    private Cut mCut;
    @Nullable
    private UtubotCutSkipper mSkipper;
    @Nullable
    private Disposable mPoll;

    @Override
    public void onNewVideo(Video item) {
        // The Apply offer of the video that just ended is stale: its one press would apply the old video's cut
        dismissReadyOffer();
        mReadyCuts = null;

        // A pick that never got the backend's confirmation only guarded the open it was made for
        if (mVideo != null && !Helpers.equals(mVideo.videoId, item != null ? item.videoId : null)) {
            mLocalPicks.remove(mVideo.videoId);
        }

        // A cut that waits to be applied is re-armed too: stopSkipping clears it, and a reload of the same video comes before the length
        // is known sometimes
        Cut rearm = mCut != null ? mCut : mPendingCut;

        if (mOpenCut != null) {
            // The picker of a video that wasn't playing yet asked for this cut of this video: it is applied as the video opens
            if (Helpers.equals(mOpenCut.videoId, item != null ? item.videoId : null)) {
                rearm = mOpenCut;
            }

            mOpenCut = null;
        }

        stopSkipping();

        if (item == null || rearm == null || !Helpers.equals(rearm.videoId, item.videoId)) {
            UtubotCutSeekBar.setCut(item == null ? null : item.videoId, null);
            mCut = null;
            mPendingCut = null; // a cut that waited for another video must not claim a different length for this one
        } else {
            // The same video plays again (a reload, the playback queue): the skipper and the poll are gone with stopSkipping, so the
            // cut is re-applied like a fresh one once the length is known
            mPendingCut = rearm;
            mCut = null;
            startPolling();
        }

        mVideo = item;
        setCutLabel(null);

        if (item != null && item.videoId != null && UtubotSettings.instance(getContext()).isConfigured()) {
            UtubotManager.instance(getContext()).followCuts(item.videoId, this);
        }
    }

    @Override
    public void onVideoLoaded(Video item) {
        tryApplyPending();
    }

    @Override
    public void onMetadata(MediaItemMetadata metadata) {
        tryApplyPending();
    }

    @Override
    public void onEngineInitialized() {
        // The seek bar was reset with the engine: a cut that stayed applied comes back on, and a cut that was still waiting for
        // the length before the release is tried again
        if (mCut != null || mPendingCut != null) {
            if (mCut != null) {
                mPendingCut = mCut;
                mCut = null;
                mSkipper = null;
            }

            startPolling();
            tryApplyPending();
        }

        // A ready-cuts answer that arrived before the engine was initialized is offered now, so a video whose cuts are already
        // built does not start uncut and lose the offer
        showReadyOffers();
    }

    @Override
    public void onSeekEnd() {
        // A seek of the user is where the playback starts from: not a crossing into a drop, even when it lands a moment inside one
        if (mSkipper != null && getPlayer() != null) {
            mSkipper.onSeek(getPlayer().getPositionMs());
        }
    }

    @Override
    public void onEngineReleased() {
        // The engine is released for a format change, a restart at the fixer, or a home round trip: the video stays and a
        // VideoLoaderController load follows with no onNewVideo, so the cut's follower must stay too (the menu's next request is
        // still followed). A cut that was ready but still waiting for the length stays pending; onEngineInitialized re-arms the
        // applied one, restarts the poll and tries the pending one. Only onFinish ends the follower.
        Cut rearm = mPendingCut;
        stopSkipping();
        mPendingCut = rearm;
    }

    @Override
    public void onFinish() {
        stopSkipping();
        mReadyCuts = null;
        mCut = null; // the playback is gone: a picker of this video from a list starts it again, with its cut carried to the player

        // A pick guarded this open only; an off still guards the next open until the viewer picks a cut here again
        if (mVideo != null) {
            mLocalPicks.remove(mVideo.videoId);
        }

        stopFollowing();
    }

    //region The follower's answers

    @Override
    public void onCutReady(String videoId, Cut cut, boolean requested) {
        Video video = getVideo();

        if (!isLivePlayer() || !Helpers.equals(videoId, video != null ? video.videoId : null)) {
            return;
        }

        // A request followed from the list can become ready after the viewer picked or turned off a cut here: that explicit choice
        // wins over the older request, like it wins over a stale cuts answer
        if (blocksSelection(videoId, cut)) {
            return;
        }

        String ready = readyText(cut);

        // A cut this TV waited for is applied from the current position; a cut that was already there when the video opened
        // is offered with a one-press Apply, unless it was picked before the video opened (then it applies by itself).
        if (requested) {
            MessageHelpers.showMessage(getContext(), ready);
            applyReadyCut(cut);
        } else if (!isApplied(cut) && !isQueued(cut)) {
            if (UtubotSettings.instance(getContext()).isApplyReadyCutsEnabled()) {
                MessageHelpers.showMessage(getContext(), ready);
                applyReadyCut(cut);
            } else {
                offerReadyCut(cut, ready);
            }
        }
    }

    @Override
    public void onCutChosen(String videoId, Cut cut) {
        if (!Helpers.equals(videoId, currentVideoId()) || isApplied(cut) || isQueued(cut)) {
            return;
        }

        // The cuts answer can still carry the choice this TV just replaced or turned off: its write is asynchronous and the
        // answer may have been built before it landed. The explicit local pick wins over that stale selection.
        if (blocksSelection(videoId, cut)) {
            return;
        }

        // The chosen cut is queued even before the player's engine is initialized (the cuts answer can land while the view
        // starts): it applies once the engine is initialized and the length is known, like a cut carried from a list
        applyCutWhenPossible(cut);
    }

    @Override
    public void onCutsReady(String videoId, List<Cut> cuts) {
        if (!Helpers.equals(videoId, currentVideoId()) || blocksOffer(videoId)) {
            return;
        }

        List<Cut> offered = new ArrayList<>();

        for (Cut cut : cuts) {
            if (!isApplied(cut) && !isQueued(cut)) {
                offered.add(cut);
            }
        }

        if (offered.isEmpty()) {
            mReadyCuts = null;
            return;
        }

        if (!isLivePlayer()) {
            // The cuts answer can land before the engine is initialized (the open runs before startView): the offer waits for
            // the player instead of being dropped
            mReadyCuts = offered;
            return;
        }

        mReadyCuts = null;
        offerReadyCuts(offered);
    }

    //endregion

    /**
     * The player button opens the cut picker of the video that plays (the video menu's picker without leaving the player)
     */
    @Override
    public void onButtonClicked(int buttonId, int buttonState) {
        Video video = getVideo();

        if (buttonId == R.id.action_utubot_cut && video != null) {
            UtubotMenu.showCuts(getContext(), video);
        }
    }

    //region The picker's actions

    /**
     * Picking the applied cut turns it off; picking a ready cut in the picker of the video that plays applies it now. The picker of
     * a video that isn't playing yet answers false: the caller starts the video with {@link #applyOnOpen(Cut)}.
     *
     * @return true when the picker acted on the video that plays (applied, turned off, queued for the length, or refused for a
     *         real length mismatch); false when no player of this video is running
     */
    public boolean toggle(Cut cut) {
        if (!isPlayingVideo(cut)) {
            // A picker opened from a list has no player of this video: nothing here to toggle, no length claim to make, and a cut
            // left in memory after an earlier playback is not "applied" to anything
            return false;
        }

        if (isApplied(cut)) {
            turnOff();
            return true;
        }

        long durationMs = getPlayer().getDurationMs();

        if (durationMs <= 0) {
            // Length not known yet: the cut waits for it, like a cut that came ready before the stream did
            noteLocalPick(cut);
            rememberCutChoice(cut);
            mPendingCut = cut;
            startPolling();
            return true;
        }

        if (!UtubotCutSkipper.matchesDuration(cut, durationMs)) {
            MessageHelpers.showLongMessage(getContext(), getContext().getString(R.string.utubot_cut_other_length));
            return true;
        }

        noteLocalPick(cut);
        rememberCutChoice(cut);
        mPendingCut = null;
        apply(cut);
        return true;
    }

    /**
     * The picker was opened for a video that isn't playing (a card of a list): this cut applies once that video opens. Another
     * video drops it; a video of another length refuses it with the plain length message.
     */
    public void applyOnOpen(Cut cut) {
        if (cut == null || cut.videoId == null) {
            return;
        }

        noteLocalPick(cut);
        rememberCutChoice(cut);
        mOpenCut = cut;
    }

    /**
     * A cut is applied to the video that plays
     */
    public boolean isApplied(Cut cut) {
        return mCut != null && Helpers.equals(mCut.videoId, cut.videoId) && Helpers.equals(mCut.label, cut.label);
    }

    /**
     * The video that plays: a destroyed view returned by the presenter, or one whose engine is released, carries the last video but is
     * no playback (a list picker for that video must start it again through {@link #applyOnOpen(Cut)}, not toggle a cut here)
     */
    private boolean isPlayingVideo(Cut cut) {
        Video video = getVideo();

        return cut != null && isLivePlayer() && video != null && Helpers.equals(video.videoId, cut.videoId);
    }

    private boolean isLivePlayer() {
        PlaybackView player = getPlayer();

        return player != null && player.isEngineInitialized();
    }

    /**
     * The video the follower is following: the open recorded it before the player existed, so a cuts answer that lands before
     * startView still matches its video
     */
    private String currentVideoId() {
        if (mVideo != null && mVideo.videoId != null) {
            return mVideo.videoId;
        }

        Video video = getVideo();

        return video != null ? video.videoId : null;
    }

    private boolean isQueued(Cut cut) {
        return mPendingCut != null && Helpers.equals(mPendingCut.videoId, cut.videoId)
                && Helpers.equals(mPendingCut.label, cut.label);
    }

    /**
     * A selection of the follower that would undo an explicit local choice whose write may still be in flight: the local pick or
     * off wins until the backend's answer carries it.
     */
    private boolean blocksSelection(String videoId, Cut cut) {
        if (videoId == null) {
            return false;
        }

        if (mLocalOffs.contains(videoId)) {
            return true;
        }

        if (!mLocalPicks.containsKey(videoId)) {
            return false;
        }

        if (choiceKey(cut).equals(mLocalPicks.get(videoId))) {
            // The backend now carries the pick: the next answer can speak for it again
            mLocalPicks.remove(videoId);
            return false;
        }

        return true;
    }

    /**
     * No offer while this TV's own pick or off has not reached the backend: a stale ready list would offer cuts the viewer just
     * replaced or turned off.
     */
    private boolean blocksOffer(String videoId) {
        return videoId != null && (mLocalOffs.contains(videoId) || mLocalPicks.containsKey(videoId));
    }

    /**
     * An explicit pick of this TV: it wins over a cuts answer that was built before the choice write landed.
     */
    private void noteLocalPick(Cut cut) {
        if (cut == null || cut.videoId == null) {
            return;
        }

        mLocalOffs.remove(cut.videoId);
        mLocalPicks.put(cut.videoId, choiceKey(cut));
    }

    /**
     * The viewer turned the cut off for this video on this TV: a stale answer must not bring a choice back while the off write is
     * still on its way.
     */
    private void noteLocalOff(@Nullable String videoId) {
        if (videoId == null) {
            return;
        }

        mLocalPicks.remove(videoId);
        mLocalOffs.add(videoId);
    }

    private static String choiceKey(Cut cut) {
        return cut.presetId != null ? cut.presetId : (cut.label != null ? cut.label : "");
    }

    private void turnOff() {
        stopSkipping();
        UtubotCutSeekBar.setCut(mVideo != null ? mVideo.videoId : null, null);
        UtubotCutSeekBar.paint(getPlayer());
        mCut = null;
        setCutLabel(null);

        if (mVideo != null && mVideo.videoId != null && UtubotSettings.instance(getContext()).isConfigured()) {
            noteLocalOff(mVideo.videoId);
            UtubotManager.instance(getContext()).forgetCutChoice(mVideo.videoId);
        }
    }

    //endregion

    private void apply(Cut cut) {
        if (!isLivePlayer()) {
            return;
        }

        mCut = cut;
        mSkipper = new UtubotCutSkipper(cut, activeSponsorSegments(), this::isSponsorSegmentSkipped);
        UtubotCutSeekBar.setCut(cut.videoId, toSeekBarSegments(cut, getPlayer().getDurationMs()));
        UtubotCutSeekBar.paint(getPlayer());
        setCutLabel(cut);
        startPolling();

        // Applying a cut is an explicit act, not a seek: when the playback is already inside a dropped range (an intro drop the video
        // plays in, or a cut picked up mid-drop), it jumps once to the end of it, with the usual Skipped toast as the undo
        long positionMs = getPlayer().getPositionMs();
        UtubotCutSkipper.Decision decision = mSkipper.onAppliedAt(positionMs);

        if (decision.isJump()) {
            skipTo(decision.jumpToMs, positionMs);
        }
    }

    /**
     * A cut waits to be applied until the length of the video is known: only a cut of the same length is one of this video
     */
    private void tryApplyPending() {
        Cut cut = mPendingCut;

        if (cut == null || !isLivePlayer()) {
            return;
        }

        Video video = getVideo();

        if (video == null || !Helpers.equals(cut.videoId, video.videoId)) {
            // The playback moved on: the old video's cut is not this video's, and its length must not be compared to this one
            mPendingCut = null;
            UtubotCutSeekBar.setCut(cut.videoId, null);
            UtubotCutSeekBar.paint(getPlayer());
            stopPolling();
            return;
        }

        long durationMs = getPlayer().getDurationMs();

        if (durationMs <= 0) {
            return; // not known yet: the poll tick tries again
        }

        mPendingCut = null;

        if (!UtubotCutSkipper.matchesDuration(cut, durationMs)) {
            Log.d(TAG, "Not applying the cut of %s: built for %s ms, the video is %s ms", cut.videoId, cut.durationMs, durationMs);
            MessageHelpers.showLongMessage(getContext(), getContext().getString(R.string.utubot_cut_other_length));
            UtubotCutSeekBar.setCut(cut.videoId, null); // a re-armed cut may have left its dims on the bar
            UtubotCutSeekBar.paint(getPlayer());
            stopPolling();
            return;
        }

        apply(cut);
    }

    private void startPolling() {
        if (mPoll != null && !mPoll.isDisposed()) {
            return;
        }

        if (!isLivePlayer()) {
            return;
        }

        // NOTE: like the sponsor block's watcher: no player access from where the interval is created
        mPoll = RxHelper.interval(POLL_INTERVAL_MS, TimeUnit.MILLISECONDS).subscribe(
                tick -> tick(),
                error -> Log.d(TAG, "The cut watcher stopped: %s", error.getMessage())
        );
    }

    private void stopPolling() {
        RxHelper.disposeActions(mPoll);
    }

    private void tick() {
        if (!isLivePlayer() || mVideo == null || mVideo.isLive) {
            return;
        }

        if (mPendingCut != null) {
            tryApplyPending();
        }

        if (mSkipper == null || mCut == null || !getPlayer().isPlaying()) {
            return;
        }

        long positionMs = getPlayer().getPositionMs();
        UtubotCutSkipper.Decision decision = mSkipper.onPosition(positionMs, getSpeed());

        if (decision.isJump()) {
            skipTo(decision.jumpToMs, positionMs);
        }
    }

    private void skipTo(long toMs, long fromMs) {
        long durationMs = getPlayer().getDurationMs();

        if (durationMs > 0) {
            toMs = Math.min(toMs, durationMs); // position may exceed real media length
        }

        if (toMs <= fromMs) {
            return;
        }

        getPlayer().setPositionMs(toMs);
        showSkippedToast(fromMs, toMs - fromMs);
    }

    /**
     * "Skipped 1:20" with a Back that returns to the skipped part, for a moment. The last drop of a cut that ends before the video
     * end says "End of cut" instead, with the same back as "Watch the rest". Nothing extra while another dialog is up.
     */
    private void showSkippedToast(long skippedFromMs, long skippedMs) {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        if (dialogPresenter.isDialogShown() || getPlayer().isSuggestionsShown()) {
            return;
        }

        getPlayer().showControls(false);

        boolean cutEnd = isCutEnd(mCut, skippedFromMs);
        long backToMs = skippedFromMs;
        OptionItem back = UiOptionItem.from(getContext().getString(
                cutEnd ? R.string.utubot_cut_watch_rest : R.string.utubot_cut_back), option -> {
            dialogPresenter.goBack();
            getPlayer().setPositionMs(backToMs);
        });

        dialogPresenter.appendSingleButton(back);
        dialogPresenter.setCloseTimeoutMs(TOAST_BACK_MS);
        dialogPresenter.enableTransparent(true);
        dialogPresenter.enableOverlay(true);
        dialogPresenter.enableExpandable(false);
        dialogPresenter.setId(CUT_DIALOG_ID);
        dialogPresenter.showDialog(cutEnd ? getContext().getString(R.string.utubot_cut_end)
                : getContext().getString(R.string.utubot_cut_skipped, formatLength(skippedMs)));
    }

    /**
     * The last dropped range of the cut reaches the video end: this jump ends the cut rather than skipping a middle drop
     */
    public static boolean isCutEnd(@Nullable Cut cut, long fromMs) {
        if (cut == null || cut.durationMs <= 0 || cut.skipRangesMs == null || cut.skipRangesMs.isEmpty()) {
            return false;
        }

        long[] last = cut.skipRangesMs.get(cut.skipRangesMs.size() - 1);

        return last[1] == cut.durationMs && fromMs >= last[0] && fromMs < last[1];
    }

    private String readyText(Cut cut) {
        return getContext().getString(R.string.utubot_cut_ready,
                cut.label != null ? cut.label : getContext().getString(R.string.utubot_cut),
                formatLength(cut.keptMs));
    }

    /**
     * No cut was chosen and the last-used preset has none ready: every ready cut is offered, none applied for the viewer. The
     * one cut is the usual one-press Apply; several are one button each, since silently picking the first is the bug.
     */
    private void offerReadyCuts(List<Cut> cuts) {
        if (cuts.size() == 1) {
            offerReadyCut(cuts.get(0), readyText(cuts.get(0)));
            return;
        }

        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());
        PlaybackView player = getPlayer();
        String title = getContext().getString(R.string.utubot_cut_ready_choice);

        if (player == null || dialogPresenter.isDialogShown() || player.isSuggestionsShown()) {
            MessageHelpers.showMessage(getContext(), title);
            return;
        }

        player.showControls(false);

        for (Cut cut : cuts) {
            OptionItem apply = UiOptionItem.from(presetTitle(cut.label != null ? cut.label : getContext().getString(R.string.utubot_cut),
                    cut.keptMs), option -> {
                dialogPresenter.goBack();
                applyReadyCut(cut);
            });
            dialogPresenter.appendSingleButton(apply);
        }

        dialogPresenter.setCloseTimeoutMs(READY_OFFER_MS);
        dialogPresenter.enableTransparent(true);
        dialogPresenter.enableOverlay(true);
        dialogPresenter.enableExpandable(false);
        dialogPresenter.setId(READY_DIALOG_ID);
        dialogPresenter.showDialog(title);
    }

    /**
     * "Director's cut ready: No filler, 12:40" with a one-press Apply. The announcement goes with the offer; a dialog that is
     * already up or the suggestions leave only the plain message, since another UI must not be taken over.
     */
    private void offerReadyCut(Cut cut, String text) {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());
        PlaybackView player = getPlayer();

        if (player == null || dialogPresenter.isDialogShown() || player.isSuggestionsShown()) {
            MessageHelpers.showMessage(getContext(), text);
            return;
        }

        player.showControls(false);

        OptionItem apply = UiOptionItem.from(getContext().getString(R.string.utubot_cut_apply), option -> {
            dialogPresenter.goBack();
            applyReadyCut(cut);
        });

        dialogPresenter.appendSingleButton(apply);
        dialogPresenter.setCloseTimeoutMs(READY_OFFER_MS);
        dialogPresenter.enableTransparent(true);
        dialogPresenter.enableOverlay(true);
        dialogPresenter.enableExpandable(false);
        dialogPresenter.setId(READY_DIALOG_ID);
        dialogPresenter.showDialog(text);
    }

    /**
     * A ready-cuts answer that waited for the engine is offered now: no cut of this video is applied or waiting, so every ready
     * cut gets its one-press button. A chosen cut that took over clears the offer instead.
     */
    private void showReadyOffers() {
        List<Cut> ready = mReadyCuts;
        mReadyCuts = null;

        if (ready == null || mCut != null || mPendingCut != null) {
            return;
        }

        List<Cut> offered = new ArrayList<>();

        for (Cut cut : ready) {
            if (!isApplied(cut) && !isQueued(cut)) {
                offered.add(cut);
            }
        }

        if (!offered.isEmpty()) {
            offerReadyCuts(offered);
        }
    }

    /**
     * The Apply offer of the video that ended is closed at the next video: the cut it carries is not the new video's
     */
    private void dismissReadyOffer() {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        if (dialogPresenter.getId() == READY_DIALOG_ID) {
            dialogPresenter.closeDialog();
        }
    }

    /**
     * Apply pressed on the announcement: the length may still be unknown, so the cut waits like any other pending one. The playback
     * may have changed while the offer was up: the cut is only applied to the video it was built for.
     */
    private void applyReadyCut(Cut cut) {
        Video video = getVideo();

        if (cut == null || !isLivePlayer() || video == null || !Helpers.equals(cut.videoId, video.videoId)) {
            return;
        }

        noteLocalPick(cut);
        rememberCutChoice(cut);
        applyCutWhenPossible(cut);
    }

    /**
     * A cut the viewer already chose (the selection of the open): applied once the length is known, without writing the choice again.
     */
    private void applyCutWhenPossible(Cut cut) {
        mPendingCut = cut;
        startPolling();
        tryApplyPending();
    }

    private void rememberCutChoice(Cut cut) {
        if (cut == null || cut.videoId == null || cut.presetId == null || getContext() == null) {
            return;
        }

        if (UtubotSettings.instance(getContext()).isConfigured()) {
            UtubotManager.instance(getContext()).rememberCutChoice(cut.videoId, cut.presetId);
        }
    }

    /**
     * The player's cut button says which cut is on: "Cut: Half · 41:20", or the plain menu label when none is.
     */
    private void setCutLabel(@Nullable Cut cut) {
        PlaybackView player = getPlayer();

        if (player == null) {
            return;
        }

        String label = cut != null && cut.label != null
                ? getContext().getString(R.string.utubot_cut_player_label, cut.label, formatLength(cut.keptMs))
                : getContext().getString(R.string.utubot_cut_menu);
        player.setButtonLabel(R.id.action_utubot_cut, label);
    }

    /**
     * The sponsor segments of the video that play, so the cut's jump goes past the ones that would jump after it
     */
    private List<SponsorSegment> activeSponsorSegments() {
        SponsorBlockController sponsorBlock = getController(SponsorBlockController.class);

        return sponsorBlock != null ? sponsorBlock.getActiveSegments() : null;
    }

    private boolean isSponsorSegmentSkipped(String category) {
        SponsorBlockData data = getSponsorBlockData();
        int action = data.getAction(category);

        return action == SponsorBlockData.ACTION_SKIP_ONLY || action == SponsorBlockData.ACTION_SKIP_WITH_TOAST;
    }

    private List<SeekBarSegment> toSeekBarSegments(Cut cut, long durationMs) {
        List<SeekBarSegment> segments = new ArrayList<>();

        if (durationMs <= 0) {
            return segments;
        }

        for (long[] range : cut.skipRangesMs) {
            SeekBarSegment segment = new SeekBarSegment();
            segment.startProgress = (float) range[0] / durationMs;
            segment.endProgress = (float) range[1] / durationMs;
            segment.color = SKIP_COLOR;
            segments.add(segment);
        }

        return segments;
    }

    private void stopSkipping() {
        stopPolling();
        mSkipper = null;
        mPendingCut = null;
    }

    /**
     * The long poll of the player's request ends with the video: not kept running past the close until ready or the cap
     */
    private void stopFollowing() {
        if (getContext() != null) {
            UtubotManager.instance(getContext()).stopFollowingCuts(this);
        }
    }

    private float getSpeed() {
        return getPlayer() != null ? getPlayer().getSpeed() : 1f;
    }

    /**
     * The preset label with the real length of its ready cut: "Highlights in 5 min · 5:02". A cut without a known length
     * (or no cut yet) is just the label.
     */
    public static String presetTitle(String label, long keptMs) {
        String length = formatLength(keptMs);

        return length.isEmpty() ? label : label + " \u00b7 " + length;
    }

    /**
     * "12:40" of a length in milliseconds
     */
    public static String formatLength(long ms) {
        if (ms < 0) {
            return "";
        }

        long seconds = ms / 1000;
        long hours = TimeUnit.SECONDS.toHours(seconds);
        long minutes = TimeUnit.SECONDS.toMinutes(seconds) % TimeUnit.HOURS.toMinutes(1);
        long rest = seconds % TimeUnit.MINUTES.toSeconds(1);

        return hours > 0 ? String.format(Locale.ROOT, "%d:%02d:%02d", hours, minutes, rest)
                : String.format(Locale.ROOT, "%d:%02d", minutes, rest);
    }

    /**
     * One kept part of a cut as the TV parts list shows it: "2:10 - 3:05  The demo"
     */
    public static String formatPart(CutPart part) {
        if (part == null) {
            return "";
        }

        String label = part.label != null ? part.label.trim() : "";

        return formatLength(part.startMs) + " - " + formatLength(part.endMs) + (label.isEmpty() ? "" : "  " + label);
    }
}