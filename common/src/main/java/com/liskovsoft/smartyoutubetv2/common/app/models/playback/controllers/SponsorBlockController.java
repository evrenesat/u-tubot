package com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import com.liskovsoft.mediaserviceinterfaces.MediaItemService;
import com.liskovsoft.mediaserviceinterfaces.ServiceManager;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemMetadata;
import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.BasePlayerController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerUI;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.SponsorBlockSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutController;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutSeekBar;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.youtubeapi.service.YouTubeServiceManager;
import io.reactivex.Observable;
import io.reactivex.disposables.Disposable;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

public class SponsorBlockController extends BasePlayerController {
    private static final String TAG = SponsorBlockController.class.getSimpleName();
    private static final long POLL_INTERVAL_MS = 1_000;
    private static final int CONTENT_BLOCK_ID = 144;
    private MediaItemService mMediaItemService;
    private List<SponsorSegment> mActiveSegments;
    private long mLastSkipPosMs;
    private boolean mSkipExclude;
    private String mToggledVideoId;
    private boolean mIsToggledVideoEnabled;
    private Disposable mSegmentsAction;
    private Observable<List<SponsorSegment>> mCachedSegmentsAction;
    private String mVideoId;

    public static class SegmentAction {
        public String segmentCategory;
        public int actionType;

        public static SegmentAction from(String spec) {
            if (spec == null) {
                return null;
            }

            String[] split = spec.split(",");

            if (split.length != 2) {
                return null;
            }

            String name = Helpers.parseStr(split[0]);
            int action = Helpers.parseInt(split[1]);

            return from(name, action);
        }

        public static SegmentAction from(String name, int action) {
            SegmentAction blockedSegment = new SegmentAction();
            blockedSegment.segmentCategory = name;
            blockedSegment.actionType = action;

            return blockedSegment;
        }

        @NonNull
        @Override
        public String toString() {
            return String.format("%s,%s", segmentCategory, actionType);
        }
    }

    @Override
    public void onInit() {
        ServiceManager service = YouTubeServiceManager.instance();
        mMediaItemService = service.getMediaItemService();
    }

    @Override
    public void onNewVideo(Video item) {
        mSkipExclude = false;
        // The toggle lasts until a different video is played. Reloads of the same video keep it.
        if (item == null || !Helpers.equals(mToggledVideoId, item.videoId)) {
            mToggledVideoId = null;
        }
        if (getPlayer() != null) {
            UtubotCutSeekBar.wipe(getPlayer(), item); // reset colors, keep a director's cut of the same video
        }
    }

    @Override
    public void onVideoLoaded(Video item) {
        disposeActions();

        if (getPlayer() == null) {
            return;
        }

        boolean enabled = isSponsorBlockEnabled(item, item != null ? item.channelId : null);
        getPlayer().setButtonState(R.id.action_content_block, enabled ? PlayerUI.BUTTON_ON : PlayerUI.BUTTON_OFF);

        if (enabled) {
            updateSponsorSegmentsAndWatch(item);
        }
    }

    @Override
    public void onMetadata(MediaItemMetadata metadata) {
        // Disable sponsor for the live streams.
        // Fix when using remote control.
        // Got channel id. Check the exclusions.
        if (!isSponsorBlockEnabled(getVideo(), metadata.getChannelId())) {
            if (getPlayer() != null) {
                getPlayer().setButtonState(R.id.action_content_block, PlayerUI.BUTTON_OFF);
            }
            disposeActions();
        }
    }

    @Override
    public void onEngineReleased() {
        disposeActions();
    }

    @Override
    public void onButtonClicked(int buttonId, int buttonState) {
        if (getPlayer() == null) {
            return;
        }

        if (buttonId == R.id.action_content_block) {
            Video video = getVideo();

            // Toggle for the current video only
            if (video != null && video.videoId != null) {
                mToggledVideoId = video.videoId;
                mIsToggledVideoEnabled = buttonState != PlayerUI.BUTTON_ON;
            }

            onVideoLoaded(video);
        }
    }

    @Override
    public void onButtonLongClicked(int buttonId, int buttonState) {
        if (buttonId == R.id.action_content_block) {
            SponsorBlockSettingsPresenter.instance(getContext()).show(() -> {
                if (getPlayer() != null) {
                    onVideoLoaded(getVideo());
                }
            });
        }
    }

    private boolean checkVideo(Video video) {
        //return video != null && !video.isLive && !video.isUpcoming;
        return video != null;
    }

    /**
     * The per-video toggle wins over the channel exclusion, which wins over the global switch
     */
    private boolean isSponsorBlockEnabled(Video video, String channelId) {
        if (!checkVideo(video)) {
            return false;
        }

        if (mToggledVideoId != null && mToggledVideoId.equals(video.videoId)) {
            return mIsToggledVideoEnabled;
        }

        return getSponsorBlockData().isSponsorBlockEnabled() && !isChannelExcluded(channelId);
    }

    private void updateSponsorSegmentsAndWatch(Video item) {
        if (item == null || item.videoId == null || item.isLive || getSponsorBlockData().getEnabledCategories().isEmpty()) {
            mActiveSegments = null;
            mCachedSegmentsAction = null;
            return;
        }

        if (!Helpers.equals(mVideoId, item.videoId) || mCachedSegmentsAction == null) {
            // NOTE: SponsorBlock (when happened java.net.SocketTimeoutException) could block whole application with Schedulers.io()
            // Because Schedulers.io() reuses blocked threads in RxJava 2: https://github.com/ReactiveX/RxJava/issues/6542
            mCachedSegmentsAction = mMediaItemService.getSponsorSegmentsObserve(item.videoId, getSponsorBlockData().getEnabledCategories())
                    .cache();
            mVideoId = item.videoId;
        }

        mSegmentsAction = mCachedSegmentsAction
                .flatMap(this::startSponsorWatcher)
                .subscribe(
                        this::skipSegment,
                        error -> Log.d(TAG, "It's ok. Nothing to block in this video. Error msg: %s", error.getMessage())
                );
    }

    private Observable<Long> startSponsorWatcher(List<SponsorSegment> segments) {
        if (getPlayer() == null || segments == null || segments.isEmpty()) {
            mActiveSegments = null;
            return Observable.empty();
        }

        mActiveSegments = new ArrayList<>(segments);

        if (getSponsorBlockData().isColorMarkersEnabled()) {
            UtubotCutSeekBar.setSponsor(getPlayer(), toSeekBarSegments(segments));
        }
        if (getSponsorBlockData().isActionsEnabled()) {
            // Warn. Try to not access player object here.
            // Or you'll get "Player is accessed on the wrong thread" error.
            return RxHelper.interval(POLL_INTERVAL_MS, TimeUnit.MILLISECONDS);
        } else {
            return Observable.empty();
        }
    }

    private void disposeActions() {
        RxHelper.disposeActions(mSegmentsAction);

        // Note, removes all segments at once
        //getPlayer().setSeekBarSegments(null); // reset colors

        // Reset previously found segment (fix no dialog popup)
        mLastSkipPosMs = 0;
    }

    /**
     * The sponsor segments of the video that plays, for the layers that keep their skips to one jump with the sponsor block's (u·tubot
     * director's cuts). Null while none are known.
     */
    public List<SponsorSegment> getActiveSegments() {
        return mActiveSegments;
    }

    /**
     * A u·tubot director's cut is applied to the video that plays: while it is, the sponsor block stays fully off (no skip, no prompt)
     * so the two do not fight over the same section (u·tubot#145). It goes off again as soon as the cut is taken off or the video has
     * no active cut.
     */
    private boolean isCutActive() {
        UtubotCutController cut = getController(UtubotCutController.class);
        return cut != null && cut.isCutActive();
    }

    private void skipSegment(long interval) {
        // A u·tubot director's cut is applied to the video that plays: the sponsor block stays fully off (no skip, no prompt) while
        // it is, so the two do not fight over the same section and their seeks clash (u·tubot#145). It comes back when the cut is
        // taken off or the video has no active cut.
        if (isCutActive()) {
            return;
        }

        if (mActiveSegments == null || mActiveSegments.isEmpty() || getVideo() == null || !Helpers.equals(mVideoId, getVideo().videoId)) {
            disposeActions();
            return;
        }

        // Fix looping messages at the end of the video (playback mode: pause at the end of the video)
        if (!getPlayer().isPlaying()) {
            return;
        }

        long positionMs = getPlayer().getPositionMs();

        List<SponsorSegment> foundSegments = findMatchedSegments(positionMs, mActiveSegments);

        applyActions(foundSegments);

        // Skip each segment only once
        if (foundSegments != null && getSponsorBlockData().isDontSkipSegmentAgainEnabled()) {
            mActiveSegments.removeAll(foundSegments);
        }
    }

    private boolean isPositionInsideSegment(long positionMs, SponsorSegment segment) {
        // NOTE: in case of using Player.setSeekParameters (inaccurate seeking) increase sponsor segment window
        // int seekShift = 1_000;
        // return positionMs >= (segment.getStartMs() - seekShift) && positionMs <= (segment.getEndMs() + seekShift);

        long windowSizeMs = (long) (2_000 * getPlayer().getSpeed());
        return positionMs >= segment.getStartMs() && positionMs <= Math.min(segment.getStartMs() + windowSizeMs, segment.getEndMs());
    }

    private void simpleSkip(long skipPosMs) {
        if (mLastSkipPosMs == skipPosMs) {
            return;
        }

        setPositionMs(skipPosMs);
        closeTransparentDialog();
    }

    private void messageSkip(long skipPosMs, String category) {
        if (mLastSkipPosMs == skipPosMs) {
            return;
        }

        MessageHelpers.showMessage(getContext(),
                String.format("%s: %s", getContext().getString(R.string.content_block_provider), getContext().getString(R.string.msg_skipping_segment, category)));
        setPositionMs(skipPosMs);
        closeTransparentDialog();
    }

    private void confirmSkip(long skipPosMs, String category) {
        if (mLastSkipPosMs == skipPosMs) {
            return;
        }

        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        if (dialogPresenter.isDialogShown() || getPlayer().isSuggestionsShown()) {
            // Another dialog is opened. Don't distract a user.
            return;
        }

        getPlayer().showControls(false);

        OptionItem acceptOption = UiOptionItem.from(
                getContext().getString(R.string.confirm_segment_skip, category),
                option -> {
                    // return to previous dialog or close if no other dialogs in stack
                    dialogPresenter.goBack();
                    setPositionMs(skipPosMs);
                }
        );

        dialogPresenter.appendSingleButton(acceptOption);
        dialogPresenter.setCloseTimeoutMs((long) ((skipPosMs - getPlayer().getPositionMs()) * getPlayer().getSpeed()));

        dialogPresenter.enableTransparent(true);
        dialogPresenter.enableOverlay(true);
        dialogPresenter.enableExpandable(false);
        dialogPresenter.setId(CONTENT_BLOCK_ID);
        dialogPresenter.showDialog(getContext().getString(R.string.content_block_provider));
    }

    private List<SeekBarSegment> toSeekBarSegments(List<SponsorSegment> segments) {
        if (segments == null) {
            return null;
        }

        List<SeekBarSegment> result = new ArrayList<>();

        for (SponsorSegment sponsorSegment : segments) {
            if (!getSponsorBlockData().isColorMarkerEnabled(sponsorSegment.getCategory())) {
                continue;
            }

            SeekBarSegment seekBarSegment = new SeekBarSegment();
            float startRatio = (float) sponsorSegment.getStartMs() / getPlayer().getDurationMs(); // Range: [0, 1]
            float endRatio = (float) sponsorSegment.getEndMs() / getPlayer().getDurationMs(); // Range: [0, 1]
            seekBarSegment.startProgress = startRatio;
            seekBarSegment.endProgress = endRatio;
            seekBarSegment.color = ContextCompat.getColor(getContext(), getSponsorBlockData().getColorRes(sponsorSegment.getCategory()));
            result.add(seekBarSegment);
        }

        return result;
    }

    /**
     * Sponsor block fix. Position may exceed real media length.
     */
    private void setPositionMs(long positionMs) {
        long durationMs = getPlayer().getDurationMs();

        // Sponsor block fix. Position may exceed real media length.
        getPlayer().setPositionMs(Math.min(positionMs, durationMs));
    }

    /**
     * Matches only the beginning of the segment
     */
    private List<SponsorSegment> findMatchedSegments(long positionMs, List<SponsorSegment> segments) {
        if (segments == null) {
            return null;
        }

        List<SponsorSegment> foundSegment = null;

        for (SponsorSegment segment : segments) {
            int action = getSponsorBlockData().getAction(segment.getCategory());
            boolean isSkipAction = action == SponsorBlockData.ACTION_SKIP_ONLY ||
                    action == SponsorBlockData.ACTION_SKIP_WITH_TOAST;
            if (foundSegment == null) {
                if (isPositionInsideSegment(positionMs, segment)) {
                    foundSegment = new ArrayList<>();
                    foundSegment.add(segment);

                    // Action grouping aren't supported for dialogs
                    if (!isSkipAction) {
                        break;
                    }
                }
            } else {
                SponsorSegment lastSegment = foundSegment.get(foundSegment.size() - 1);
                if (isSkipAction && isPositionInsideSegment(lastSegment.getEndMs() + 3_000, segment)) {
                    foundSegment.add(segment);
                }
            }
        }

        return foundSegment;
    }

    private void applyActions(List<SponsorSegment> foundSegments) {
        if (getPlayer() == null || foundSegments == null) {
            mLastSkipPosMs = 0;
            return;
        }

        SponsorSegment lastSegment = foundSegments.get(foundSegments.size() - 1);

        Integer resId = getSponsorBlockData().getLocalizedRes(lastSegment.getCategory());
        String skipMessage = resId != null ? getContext().getString(resId) : lastSegment.getCategory();

        int type = getSponsorBlockData().getAction(lastSegment.getCategory());

        long skipPosMs = lastSegment.getEndMs();
        // Fix infinite skip loop by ignoring short segments. TextureView has a seek bug.
        long skipDurationMs = Math.min(skipPosMs, getPlayer().getDurationMs()) - getPlayer().getPositionMs();
        boolean isDurationIgnored = (skipDurationMs < 10_000 && getPlayerTweaksData().isTextureViewEnabled())
                || (skipDurationMs < getSponsorBlockData().getIgnoredDurationMs());

        if (!isDurationIgnored) {
            if (type == SponsorBlockData.ACTION_SKIP_ONLY || getPlayer().isInPIPMode() || Utils.isScreenOff(getContext()) || isEmbedPlayer()) {
                simpleSkip(skipPosMs);
            } else if (type == SponsorBlockData.ACTION_SKIP_WITH_TOAST) {
                messageSkip(skipPosMs, skipMessage);
            } else if (type == SponsorBlockData.ACTION_SHOW_DIALOG) {
                confirmSkip(skipPosMs, skipMessage);
            }
        }

        mLastSkipPosMs = skipPosMs;
    }

    private void closeTransparentDialog() {
        AppDialogPresenter dialogPresenter = AppDialogPresenter.instance(getContext());

        if (dialogPresenter.isDialogShown() && dialogPresenter.getId() == CONTENT_BLOCK_ID) {
            dialogPresenter.closeDialog();
        }
    }

    private boolean isChannelExcluded(String channelId) {
        return !mSkipExclude && getSponsorBlockData().isChannelExcluded(channelId);
    }
}
