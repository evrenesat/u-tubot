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
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.sharedutils.rx.RxHelper;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
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
    private static final int CUT_DIALOG_ID = 154;
    /** The colour of the skipped parts on the seek bar: dimmed, clearly not a sponsor block category */
    private static final int SKIP_COLOR = 0x99607080;
    @Nullable
    private Video mVideo;
    @Nullable
    private Cut mPendingCut;
    @Nullable
    private Cut mCut;
    @Nullable
    private UtubotCutSkipper mSkipper;
    @Nullable
    private Disposable mPoll;

    @Override
    public void onNewVideo(Video item) {
        stopSkipping();

        if (item == null || mCut == null || !Helpers.equals(mCut.videoId, item.videoId)) {
            UtubotCutSeekBar.setCut(item == null ? null : item.videoId, null);
            mCut = null;
        }

        mVideo = item;
        mPendingCut = null;

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
        // The seek bar was reset with the engine: a cut that stayed applied comes back on
        if (mCut != null) {
            mPendingCut = mCut;
            mCut = null;
            mSkipper = null;
            startPolling();
            tryApplyPending();
        }
    }

    @Override
    public void onSeekEnd() {
        // A seek of the user is where the playback starts from: not a crossing into a drop
        if (mSkipper != null && getPlayer() != null) {
            mSkipper.onPosition(getPlayer().getPositionMs(), getSpeed());
        }
    }

    @Override
    public void onEngineReleased() {
        stopSkipping();
    }

    @Override
    public void onFinish() {
        stopSkipping();
    }

    //region The follower's answers

    @Override
    public void onCutReady(String videoId, Cut cut, boolean requested) {
        if (getPlayer() == null || !Helpers.equals(videoId, mVideo != null ? mVideo.videoId : null)) {
            return;
        }

        // A cut that came ready with the video is offered; one this TV waited for is applied from the current position
        MessageHelpers.showMessage(getContext(), getContext().getString(R.string.utubot_cut_ready,
                cut.label != null ? cut.label : getContext().getString(R.string.utubot_cut),
                formatLength(cut.keptMs)));

        if (requested) {
            mPendingCut = cut;
            startPolling();
            tryApplyPending();
        }
    }

    //endregion

    //region The picker's actions

    /**
     * Applies a ready cut now (the picker's row), or takes an applied one off again
     */
    public void toggle(Cut cut) {
        if (isApplied(cut)) {
            turnOff();
            return;
        }

        if (getPlayer() == null || !UtubotCutSkipper.matchesDuration(cut, getPlayer().getDurationMs())) {
            MessageHelpers.showLongMessage(getContext(), getContext().getString(R.string.utubot_cut_other_length));
            return;
        }

        mPendingCut = null;
        apply(cut);
    }

    /**
     * A cut is applied to the video that plays
     */
    public boolean isApplied(Cut cut) {
        return mCut != null && Helpers.equals(mCut.videoId, cut.videoId) && Helpers.equals(mCut.label, cut.label);
    }

    private void turnOff() {
        stopSkipping();
        UtubotCutSeekBar.setCut(mVideo != null ? mVideo.videoId : null, null);
        mCut = null;
    }

    //endregion

    private void apply(Cut cut) {
        if (getPlayer() == null) {
            return;
        }

        mCut = cut;
        mSkipper = new UtubotCutSkipper(cut, activeSponsorSegments(), this::isSponsorSegmentSkipped);
        mSkipper.onPosition(getPlayer().getPositionMs(), getSpeed());
        UtubotCutSeekBar.setCut(cut.videoId, toSeekBarSegments(cut, getPlayer().getDurationMs()));
        startPolling();
    }

    /**
     * A cut waits to be applied until the length of the video is known: only a cut of the same length is one of this video
     */
    private void tryApplyPending() {
        Cut cut = mPendingCut;

        if (cut == null || getPlayer() == null) {
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
            stopPolling();
            return;
        }

        apply(cut);
    }

    private void startPolling() {
        if (mPoll != null && !mPoll.isDisposed()) {
            return;
        }

        if (getPlayer() == null) {
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
        if (getPlayer() == null || mVideo == null || mVideo.isLive) {
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
     * "Skipped 1:20" with a Back that returns to the skipped part, for a moment. Nothing extra while another dialog is up.
     */
    private void showSkippedToast(long skippedFromMs, long skippedMs) {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        if (dialogPresenter.isDialogShown() || getPlayer().isSuggestionsShown()) {
            return;
        }

        getPlayer().showControls(false);

        long backToMs = skippedFromMs;
        OptionItem back = UiOptionItem.from(getContext().getString(R.string.utubot_cut_back), option -> {
            dialogPresenter.goBack();
            getPlayer().setPositionMs(backToMs);
        });

        dialogPresenter.appendSingleButton(back);
        dialogPresenter.setCloseTimeoutMs(TOAST_BACK_MS);
        dialogPresenter.enableTransparent(true);
        dialogPresenter.enableOverlay(true);
        dialogPresenter.enableExpandable(false);
        dialogPresenter.setId(CUT_DIALOG_ID);
        dialogPresenter.showDialog(getContext().getString(R.string.utubot_cut_skipped, formatLength(skippedMs)));
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

    private float getSpeed() {
        return getPlayer() != null ? getPlayer().getSpeed() : 1f;
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
}