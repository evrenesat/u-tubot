package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu;

import android.content.Context;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotMenu;
import com.liskovsoft.mediaserviceinterfaces.MediaItemService;
import com.liskovsoft.mediaserviceinterfaces.ServiceManager;
import com.liskovsoft.mediaserviceinterfaces.data.FeedbackEndpoint;
import com.liskovsoft.mediaserviceinterfaces.data.FeedbackReasons.FeedbackItem;
import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemMetadata;
import com.liskovsoft.mediaserviceinterfaces.data.PlaylistInfo;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Playlist;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers.CommentsController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers.VideoStateController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerUI;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService.State;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.ChannelPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.ChannelUploadsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.AiSListReportPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.providers.ContextMenuManager;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.providers.ContextMenuProvider;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.FilterExclusionSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.KeywordFilterSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.ChannelUploadsView;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.misc.KeywordFilter;
import com.liskovsoft.smartyoutubetv2.common.misc.MediaServiceManager;
import com.liskovsoft.smartyoutubetv2.common.misc.NotInterestedManager;
import com.liskovsoft.smartyoutubetv2.common.misc.StreamReminderService;
import com.liskovsoft.smartyoutubetv2.common.misc.WatchLaterManager;
import com.liskovsoft.smartyoutubetv2.common.prefs.BlockedChannelData;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HiddenVideosData;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.utils.AppDialogUtil;
import com.liskovsoft.youtubeapi.service.YouTubeServiceManager;
import io.reactivex.Observable;
import io.reactivex.disposables.Disposable;

import java.lang.ref.WeakReference;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class VideoMenuPresenter extends BaseMenuPresenter {
    private static final String TAG = VideoMenuPresenter.class.getSimpleName();
    private final MediaItemService mMediaItemService;
    private final AppDialogPresenter mDialogPresenter;
    private final MediaServiceManager mServiceManager;
    private Disposable mNotInterestedAction;
    private Disposable mSubscribeAction;
    private Disposable mLikeAction;
    private Disposable mPlaylistsInfoAction;
    private Video mVideo;
    public static WeakReference<Video> sVideoHolder = new WeakReference<>(null);
    private boolean mIsNotInterestedButtonEnabled;
    private boolean mIsNotRecommendChannelEnabled;
    private boolean mIsBlockChannelEnabled;
    private boolean mIsReportAiChannelEnabled;
    private boolean mIsHideKeywordsEnabled;
    private boolean mIsExcludeChannelFromHidingEnabled;
    private boolean mIsRemoveFromHistoryButtonEnabled;
    private boolean mIsHideButtonEnabled;
    private boolean mIsOpenChannelButtonEnabled;
    private boolean mIsOpenChannelUploadsButtonEnabled;
    private boolean mIsSubscribeButtonEnabled;
    private boolean mIsShareLinkButtonEnabled;
    private boolean mIsShareQRLinkButtonEnabled;
    private boolean mIsShareEmbedLinkButtonEnabled;
    private boolean mIsAddToWatchLaterButtonEnabled;
    private boolean mIsLikeButtonEnabled;
    private boolean mIsAddToPlaylistButtonEnabled;
    private boolean mIsAddToRecentPlaylistButtonEnabled;
    private boolean mIsReturnToBackgroundVideoEnabled;
    private boolean mIsOpenPlaylistButtonEnabled;
    private boolean mIsAddToPlaybackQueueButtonEnabled;
    private boolean mIsPlayNextButtonEnabled;
    private boolean mIsShowPlaybackQueueButtonEnabled;
    private boolean mIsOpenDescriptionButtonEnabled;
    private boolean mIsOpenCommentsButtonEnabled;
    private boolean mIsPlayVideoButtonEnabled;
    private boolean mIsPlayVideoIncognitoButtonEnabled;
    private boolean mIsPlayFromStartButtonEnabled;
    private boolean mIsPlaylistOrderButtonEnabled;
    private boolean mIsStreamReminderButtonEnabled;
    private boolean mIsMarkAsWatchedButtonEnabled;
    private VideoMenuCallback mCallback;
    // MainUIData.MENU_VIDEOS until the card is known: read as the parent's constructor runs (see updateEnabledMenuItems)
    private int mMenu;
    private List<PlaylistInfo> mPlaylistInfos;
    private final Map<Long, MenuAction> mMenuMapping = new HashMap<>();

    public interface VideoMenuCallback {
        int ACTION_UNDEFINED = 0;
        int ACTION_UNSUBSCRIBE = 1;
        int ACTION_REMOVE = 2;
        int ACTION_REMOVE_FROM_PLAYLIST = 3;
        int ACTION_REMOVE_FROM_QUEUE = 4;
        int ACTION_ADD_TO_QUEUE = 5;
        int ACTION_PLAY_NEXT = 6;
        int ACTION_REMOVE_AUTHOR = 7;
        int ACTION_HIDE = 8; // hidden with Hide (see HiddenVideosData): it goes from where it's shown
        void onItemAction(Video videoItem, int action);
    }

    public static class MenuAction {
        private final Runnable mAction;
        private final boolean mIsAuth;

        public MenuAction(Runnable action, boolean isAuth) {
            this.mAction = action;
            this.mIsAuth = isAuth;
        }

        public void run() {
            mAction.run();
        }

        public boolean isAuth() {
            return mIsAuth;
        }
    }

    private VideoMenuPresenter(Context context) {
        super(context);
        ServiceManager service = YouTubeServiceManager.instance();
        mMediaItemService = service.getMediaItemService();
        mServiceManager = MediaServiceManager.instance();
        mDialogPresenter = AppDialogPresenter.instance(context);

        initMenuMapping();
    }

    public static VideoMenuPresenter instance(Context context) {
        return new VideoMenuPresenter(context);
    }

    @Override
    protected Video getVideo() {
        return mVideo;
    }

    @Override
    protected int getMenu() {
        return mMenu;
    }

    @Override
    protected AppDialogPresenter getDialogPresenter() {
        return mDialogPresenter;
    }

    @Override
    protected VideoMenuCallback getCallback() {
        return mCallback;
    }

    public void showMenu(Video video, VideoMenuCallback callback) {
        mCallback = callback;
        showMenu(video);
    }

    public void showMenu(Video video) {
        if (video == null) {
            return;
        }

        mVideo = video;
        sVideoHolder = new WeakReference<>(video);

        BrowsePresenter presenter = BrowsePresenter.instance(getContext());
        boolean inBrowse = presenter.inForeground();
        mMenu = getCardMenu(video, inBrowse && presenter.isHistorySection(), inBrowse && presenter.isPlaylistsSection());
        updateEnabledMenuItems();

        MediaServiceManager.instance().authCheck(this::bootstrapPrepareAndShowDialogSigned, this::prepareAndShowDialogUnsigned);
    }

    /**
     * The menu of the card (see MainUIData.MENU_VIDEOS...), by where it is. The section of the sidebar shown counts as where
     * when the browse view is on top: it's where the items of the History and the Playlists sections show up.
     */
    static int getCardMenu(Video video, boolean isHistorySection, boolean isPlaylistsSection) {
        if (video.belongsToSubscriptions() || video.belongsToNotifications()) {
            return MainUIData.MENU_SUBSCRIPTIONS;
        }

        if (video.belongsToHistory() || isHistorySection) {
            return MainUIData.MENU_HISTORY;
        }

        if (isPlaylistsSection) {
            return MainUIData.MENU_PLAYLISTS;
        }

        return MainUIData.MENU_VIDEOS;
    }

    private void bootstrapPrepareAndShowDialogSigned() {
        mPlaylistInfos = null;
        RxHelper.disposeActions(mPlaylistsInfoAction);
        if (isAddToRecentPlaylistButtonEnabled()) {
            mPlaylistsInfoAction = mMediaItemService.getPlaylistsInfoObserve(mVideo.videoId)
                    .subscribe(
                            videoPlaylistInfos -> {
                                mPlaylistInfos = videoPlaylistInfos;
                                prepareAndShowDialogSigned();
                            },
                            error -> Log.e(TAG, "Add to recent playlist error: %s", error.getMessage())
                    );
        } else {
            prepareAndShowDialogSigned();
        }
    }

    private void prepareAndShowDialogSigned() {
        if (getContext() == null) {
            return;
        }

        appendReturnToBackgroundVideoButton();
        UtubotMenu.append(getContext(), mDialogPresenter, mVideo);

        for (Long menuItem : MainUIData.instance(getContext()).getMenuItemsOrdered(mMenu)) {
            MenuAction menuAction = mMenuMapping.get(menuItem);
            if (menuAction != null) {
                menuAction.run();
            }
        }

        if (!mDialogPresenter.isEmpty()) {
            String title = mVideo != null ? mVideo.getTitle() : null;
            // No need to add author because: 1) This could be a channel card. 2) This info isn't so important.
            mDialogPresenter.showDialog(title);
        }
    }

    private void prepareAndShowDialogUnsigned() {
        if (getContext() == null) {
            return;
        }

        appendReturnToBackgroundVideoButton();
        UtubotMenu.append(getContext(), mDialogPresenter, mVideo);

        for (Long menuItem : MainUIData.instance(getContext()).getMenuItemsOrdered(mMenu)) {
            MenuAction menuAction = mMenuMapping.get(menuItem);
            if (menuAction != null && !menuAction.isAuth()) {
                menuAction.run();
            }
        }

        if (!mDialogPresenter.isEmpty()) {
            String title = mVideo != null ? mVideo.getTitle() : null;
            mDialogPresenter.showDialog(title);
        }
    }

    private void appendAddToWatchLaterButton() {
        if (!mIsAddToWatchLaterButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.hasVideo() || mVideo.isPlaylistAsChannel()) {
            return;
        }

        boolean isInWatchLater = WatchLaterManager.instance(getContext()).isInWatchLater(mVideo.videoId);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(isInWatchLater ? R.string.remove_video_to_watch_later : R.string.add_video_to_watch_later),
                        optionItem -> {
                            MediaServiceManager.instance().addRemoveFromWatchLaterPlaylist(mVideo, !isInWatchLater);
                            mDialogPresenter.closeDialog();
                        }
                ));
    }

    private void appendLikeButton() {
        if (!mIsLikeButtonEnabled || mVideo == null || !mVideo.hasVideo()) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(R.string.like_remove_like),
                        optionItem -> {
                            mDialogPresenter.closeDialog();
                            // The card doesn't know whether the video is liked: only its metadata does
                            MessageHelpers.showMessage(getContext(), R.string.wait_data_loading);
                            mServiceManager.loadMetadata(mVideo, this::toggleLike,
                                    error -> MessageHelpers.showLongMessage(getContext(), error.getMessage()), null);
                        }
                ));
    }

    private void toggleLike(MediaItemMetadata metadata) {
        boolean isLiked = metadata.getLikeStatus() == MediaItemMetadata.LIKE_STATUS_LIKE;
        MediaItem item = mVideo.mediaItem != null ? mVideo.mediaItem : mVideo.toMediaItem();

        RxHelper.disposeActions(mLikeAction);

        mLikeAction = RxHelper.execute(isLiked ? mMediaItemService.removeLikeObserve(item) : mMediaItemService.setLikeObserve(item),
                error -> MessageHelpers.showLongMessage(getContext(), error.getMessage()),
                () -> MessageHelpers.showMessage(getContext(), isLiked ? R.string.action_like_unset : R.string.action_like));
    }

    private void appendAddToPlaylistButton() {
        if (!mIsAddToPlaylistButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.hasVideo() || mVideo.isPlaylistAsChannel()) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(R.string.dialog_add_to_playlist),
                        optionItem -> AppDialogUtil.showAddToPlaylistDialog(getContext(), mVideo, mCallback)
                ));
    }

    private void appendAddToRecentPlaylistButton() {
        if (!isAddToRecentPlaylistButtonEnabled()) {
            return;
        }

        String playlistId = GeneralData.instance(getContext()).getLastPlaylistId();
        String playlistTitle = GeneralData.instance(getContext()).getLastPlaylistTitle();

        if (playlistId == null || playlistTitle == null) {
            return;
        }

        appendSimpleAddToRecentPlaylistButton(playlistId, playlistTitle);
    }

    private boolean isAddToRecentPlaylistButtonEnabled() {
        return mIsAddToPlaylistButtonEnabled && mIsAddToRecentPlaylistButtonEnabled && mVideo != null && mVideo.hasVideo();
    }

    private void appendSimpleAddToRecentPlaylistButton(String playlistId, String playlistTitle) {
        if (mPlaylistInfos == null) {
            return;
        }

        boolean isSelected = false;
        for (PlaylistInfo playlistInfo : mPlaylistInfos) {
            if (playlistInfo.getPlaylistId().equals(playlistId)) {
                isSelected = playlistInfo.isSelected();
                break;
            }
        }
        boolean add = !isSelected;
        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(
                        add ? R.string.dialog_add_to : R.string.dialog_remove_from, playlistTitle),
                        optionItem -> addRemoveFromPlaylist(playlistId, playlistTitle, add)
                )
        );
    }

    private void appendOpenChannelButton() {
        if (!mIsOpenChannelButtonEnabled) {
            return;
        }

        if (!ChannelPresenter.canOpenChannel(mVideo)) {
            return;
        }

        // Prepare to special type of channels that work as playlist
        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(
                        mVideo.isPlaylistAsChannel() ? R.string.open_playlist : R.string.open_channel), optionItem -> {
                    MediaServiceManager.chooseChannelPresenter(getContext(), mVideo);
                    mDialogPresenter.closeDialog();
                }));
    }

    private void appendOpenPlaylistButton() {
        if (!mIsOpenPlaylistButtonEnabled) {
            return;
        }

        // Check view to allow open playlist in grid
        if (mVideo == null || !mVideo.hasPlaylist() || (getViewManager().getTopView() == ChannelUploadsView.class && mVideo.belongsToSamePlaylistGroup())) {
            return;
        }

        // Prepare to special type of channels that work as playlist
        if (mVideo.isPlaylistAsChannel() && ChannelPresenter.canOpenChannel(mVideo)) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.open_playlist), optionItem -> ChannelUploadsPresenter.instance(getContext()).openChannel(mVideo)));
    }

    private void appendOpenChannelUploadsButton() {
        if (!mIsOpenChannelUploadsButtonEnabled || mVideo == null) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.open_channel_uploads), optionItem -> ChannelUploadsPresenter.instance(getContext()).openChannel(mVideo)));
    }

    private void appendNotInterestedButton() {
        FeedbackEndpoint feedbackEndpoint = getFeedbackEndpoint();

        // The own token of a card of Subscriptions is its removal from there (see getFeedbackEndpoint)
        if (mVideo == null || mVideo.mediaItem == null
                || (feedbackEndpoint == null && (mVideo.belongsToSubscriptions() || mVideo.mediaItem.getFeedbackToken() == null))) {
            return;
        }

        if ((!mVideo.belongsToHomeLikeSection() && !mVideo.belongsToShorts() && !mVideo.belongsToSubscriptions())
                || !mIsNotInterestedButtonEnabled) {
            return;
        }

        RxHelper.disposeActions(mNotInterestedAction);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.not_interested), optionItem -> {
                    if (feedbackEndpoint == null) {
                        markAsNotInterested(mVideo.mediaItem.getFeedbackToken());
                    } else {
                        mNotInterestedAction = mMediaItemService.getFeedbackTokensObserve(feedbackEndpoint)
                                .subscribe(
                                        tokens -> {
                                            if (tokens.size() == 2) {
                                                markAsNotInterested(tokens.get(0));
                                            }
                                        },
                                        error -> Log.e(TAG, "Mark as 'not interested' error: %s", error.getMessage())
                                );
                    }
                }));
    }

    private void markAsNotInterested(String feedbackToken) {
        mNotInterestedAction = mMediaItemService.getFeedbackReasonsObserve(feedbackToken)
                .subscribe(
                        reasons -> {
                            removeFromSubscriptionsFeed();

                            if (reasons.getItems() != null) {
                                for (FeedbackItem item : reasons.getItems()) {
                                    mDialogPresenter.appendSingleButton(
                                            UiOptionItem.from(item.getTitle(),
                                                    option -> {
                                                        RxHelper.execute(mMediaItemService.markAsNotInterestedObserve(item.getToken()));
                                                        removeSuggestedItemAndClose();
                                                    }
                                            )
                                    );
                                }
                                mDialogPresenter.showDialog(reasons.getTitle());
                            } else {
                                removeSuggestedItemAndClose();
                            }
                        },
                        error -> Log.e(TAG, "Mark as 'not interested' error: %s", error.getMessage())
                );
    }

    /**
     * Marked "Not interested" in Subscriptions: YouTube takes it out of the feed too, with the card's own feedback (YouTube's Hide)
     */
    private void removeFromSubscriptionsFeed() {
        if (mVideo == null || !mVideo.belongsToSubscriptions() || mVideo.mediaItem == null || mVideo.mediaItem.getFeedbackToken() == null) {
            return;
        }

        RxHelper.execute(mMediaItemService.markAsNotInterestedObserve(mVideo.mediaItem.getFeedbackToken()));
    }

    /**
     * The sections loaded like Home (e.g. Gaming) don't send the feedback, so their videos get the one of the Home context menu.
     * So do the videos of Subscriptions: their own feedback is the removal from there (see removeFromSubscriptionsFeed).
     * Not the playlists: their video id is the first video's, so the feedback would be about it.
     */
    private FeedbackEndpoint getFeedbackEndpoint() {
        if (mVideo == null || mVideo.mediaItem == null) {
            return null;
        }

        MediaItem mediaItem = mVideo.mediaItem;
        boolean isHomeFeedback = mVideo.hasVideo() && mediaItem.getType() == MediaItem.TYPE_VIDEO;

        if (mVideo.belongsToSubscriptions()) {
            return isHomeFeedback ? mMediaItemService.getHomeFeedbackEndpoint(mVideo.videoId) : null;
        }

        if (mediaItem.getFeedbackEndpoint() != null || mediaItem.getFeedbackToken() != null || mediaItem.getFeedbackToken2() != null
                || !mVideo.belongsToHomeLikeSection() || !isHomeFeedback) {
            return mediaItem.getFeedbackEndpoint();
        }

        return mMediaItemService.getHomeFeedbackEndpoint(mVideo.videoId);
    }

    private void removeSuggestedItemAndClose() {
        // Before the callback: the same video goes from the other rows too
        NotInterestedManager.instance().addVideo(mVideo);

        if (mCallback != null) {
            mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE);
        } else {
            MessageHelpers.showMessage(getContext(), R.string.you_wont_see_this_video);
        }
        mDialogPresenter.closeDialog();
    }

    private void appendNotRecommendChannelButton() {
        FeedbackEndpoint feedbackEndpoint = getFeedbackEndpoint();

        if (mVideo == null || mVideo.mediaItem == null || (mVideo.mediaItem.getFeedbackToken2() == null && feedbackEndpoint == null)) {
            return;
        }

        if ((!mVideo.belongsToHomeLikeSection() && !mVideo.belongsToShorts()) || !mIsNotRecommendChannelEnabled) {
            return;
        }

        RxHelper.disposeActions(mNotInterestedAction);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.not_recommend_channel), optionItem -> {
                    if (feedbackEndpoint == null) {
                        markAsNotRecommendChannel(mVideo.mediaItem.getFeedbackToken2());
                    } else {
                        mNotInterestedAction = mMediaItemService.getFeedbackTokensObserve(feedbackEndpoint)
                                .subscribe(
                                        tokens -> {
                                            if (tokens.size() == 2) {
                                                markAsNotRecommendChannel(tokens.get(1));
                                            }
                                        },
                                        error -> Log.e(TAG, "Mark as 'not interested' error: %s", error.getMessage())
                                );
                    }
                }));
    }

    private void markAsNotRecommendChannel(String feedbackToken2) {
        mNotInterestedAction = mMediaItemService.markAsNotInterestedObserve(feedbackToken2)
                .subscribe(
                        var -> {},
                        error -> Log.e(TAG, "Mark as 'not interested' error: %s", error.getMessage()),
                        () -> {
                            // Before the callback: the channel's videos go from the other rows too
                            NotInterestedManager.instance().addChannel(mVideo);

                            if (mCallback != null) {
                                mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE);
                            } else {
                                MessageHelpers.showMessage(getContext(), R.string.you_wont_see_this_video);
                            }
                        }
                );
        mDialogPresenter.closeDialog();
    }

    private void appendBlockChannelButton() {
        if (mVideo == null || mVideo.isChapter || !mIsBlockChannelEnabled) {
            return;
        }

        String channelId = mVideo.channelId;
        String channelName = mVideo.getAuthor();

        if (channelName == null) {
            return;
        }

        BlockedChannelData blockedChannelData = BlockedChannelData.instance(getContext());
        boolean isBlocked = blockedChannelData.containsChannel(channelId, channelName);

        String buttonText = isBlocked
                ? getContext().getString(R.string.dialog_unblock_channel)
                : getContext().getString(R.string.dialog_block_channel);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(buttonText, optionItem -> {
                    if (isBlocked) {
                        blockedChannelData.removeChannel(channelId, channelName);
                        MessageHelpers.showMessage(getContext(), R.string.channel_unblocked);
                    } else {
                        blockedChannelData.addChannel(channelId, channelName);
                        MessageHelpers.showMessage(getContext(), R.string.channel_blocked);
                    }

                    if (mCallback != null) {
                        mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE);
                    }
                    mDialogPresenter.closeDialog();
                    showHideBlockedChannelsSection(blockedChannelData);
                }));
    }

    /**
     * To AiSList, with the video as the evidence (see AiSListReportPresenter)
     */
    private void appendReportAiChannelButton() {
        if (mVideo == null || mVideo.isChapter || !mVideo.hasVideo() || !mIsReportAiChannelEnabled) {
            return;
        }

        Video video = mVideo;
        VideoMenuCallback callback = mCallback;

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.report_ai_channel), optionItem ->
                        AiSListReportPresenter.instance(getContext()).report(video, () -> {
                            // Blocked too: the video goes now, as with Block the channel
                            if (callback != null) {
                                callback.onItemAction(video, VideoMenuCallback.ACTION_REMOVE);
                            }
                        })));
    }

    /**
     * The words of the title to hide the videos with (see KeywordFilter)
     */
    private void appendHideKeywordsButton() {
        if (mVideo == null || mVideo.isChapter || !mVideo.hasVideo() || !mIsHideKeywordsEnabled) {
            return;
        }

        List<String> words = KeywordFilter.getTitleWords(mVideo.getTitle());

        if (words.isEmpty()) {
            return;
        }

        Video video = mVideo;
        VideoMenuCallback callback = mCallback;
        String title = getContext().getString(R.string.keyword_filter_hide_words);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(title, optionItem -> KeywordFilterSettingsPresenter.instance(getContext()).showWords(title, words, () -> {
                    // Like Block channel: the video goes now, the others with the word on the next load
                    VideoGroup group = video.getGroup();

                    if (callback != null && group != null && group.hasHiddenKeyword(video)) {
                        callback.onItemAction(video, VideoMenuCallback.ACTION_REMOVE);
                    }
                })));
    }

    /**
     * The filters of Hide or mark content set to hide that the channel is excluded from: its videos are marked instead.
     * On any card of the channel: its hidden videos have none (see FilterExclusionSettingsPresenter).
     */
    private void appendExcludeChannelFromHidingButton() {
        if (mVideo == null || mVideo.isChapter || mVideo.isShow || !mIsExcludeChannelFromHidingEnabled) {
            return;
        }

        // A video or a channel. A playlist card would give its own title as the channel.
        if (!mVideo.hasVideo() && (!mVideo.isChannel() || mVideo.isPlaylistAsChannel())) {
            return;
        }

        String channelId = mVideo.channelId;
        String channelName = mVideo.getAuthor();

        if (channelName == null || FilterExclusionSettingsPresenter.getHidingFilters(getContext()).isEmpty()) {
            return;
        }

        Context context = getContext();
        VideoGroup group = mVideo.getGroup();
        // A section is loaded again, for the videos to show or go. Search and the channel pages have them on their next load.
        Runnable onChanged = group != null && group.getSection() != null ? () -> BrowsePresenter.instance(context).refresh(false) : null;

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.exclude_channel_from_hiding),
                        optionItem -> FilterExclusionSettingsPresenter.instance(context).show(channelId, channelName, onChanged)));
    }

    private void showHideBlockedChannelsSection(BlockedChannelData blockedChannelData) {
        if (blockedChannelData.getChannelCount() == 1) { // show on add first channel
            BrowsePresenter.instance(getContext()).enableSection(MediaGroup.TYPE_BLOCKED_CHANNELS, true);
        } else if (blockedChannelData.isEmpty()) { // hide on remove all
            BrowsePresenter.instance(getContext()).enableSection(MediaGroup.TYPE_BLOCKED_CHANNELS, false);
        }
    }

    private void appendRemoveFromHistoryButton() {
        if (mVideo == null || !mVideo.belongsToHistory() || !mIsRemoveFromHistoryButtonEnabled) {
            return;
        }

        RxHelper.disposeActions(mNotInterestedAction);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.remove_from_history), optionItem -> {
                    if (mVideo.mediaItem == null || mVideo.mediaItem.getFeedbackToken() == null) {
                        onRemoveFromHistoryDone();
                    } else {
                        mNotInterestedAction = mMediaItemService.markAsNotInterestedObserve(mVideo.mediaItem.getFeedbackToken())
                                .subscribe(
                                        var -> {},
                                        error -> Log.e(TAG, "Remove from history error: %s", error.getMessage()),
                                        this::onRemoveFromHistoryDone
                                );
                    }
                    mDialogPresenter.closeDialog();
                }));
    }

    private void onRemoveFromHistoryDone() {
        if (mCallback != null) {
            mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE);
        } else {
            MessageHelpers.showMessage(getContext(), R.string.removed_from_history);
        }
        VideoStateService stateService = VideoStateService.instance(getContext());
        stateService.removeByVideoId(mVideo.videoId);
    }

    /**
     * The app's own, kept on the device (see HiddenVideosData): hidden from the section it's in, shown again from the Unhide section.
     * There it's Unhide, whatever the menu has: that's what the section is for.
     */
    private void appendHideButton() {
        VideoGroup group = mVideo != null ? mVideo.getGroup() : null; // read once: a weak reference

        if (group == null || !VideoGroup.isHideableCard(mVideo)) {
            return;
        }

        HiddenVideosData data = HiddenVideosData.instance(getContext());

        if (mVideo.belongsToHiddenVideos()) {
            int sectionId = group.getHiddenFromSection();

            mDialogPresenter.appendSingleButton(
                    UiOptionItem.from(getContext().getString(R.string.unhide), optionItem -> {
                        data.unhide(sectionId, mVideo.videoId);
                        if (mCallback != null) {
                            mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE);
                        }
                        mDialogPresenter.closeDialog();
                    }));
            return;
        }

        int sectionId = group.getHiddenVideosSection();

        if (!mIsHideButtonEnabled || !HiddenVideosData.isSupportedSection(sectionId)) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.hide_local), optionItem -> {
                    data.hide(sectionId, getHiddenVideosSectionTitle(group), mVideo);
                    if (mCallback != null) {
                        mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_HIDE);
                    }
                    mDialogPresenter.closeDialog();
                }));
    }

    /**
     * For the row of the Unhide section of a pinned section (e.g. a channel) that's gone from the sidebar. The section's title, but
     * for the subscription groups, which are one row. Not BrowseSection.isDefault: the hash id of a pinned one can be negative.
     */
    private static String getHiddenVideosSectionTitle(VideoGroup group) {
        BrowseSection section = group.getSection();

        return section != null && !section.isChannelGroup() ? section.getTitle() : null;
    }

    private void appendMarkAsWatchedButton() {
        if (mVideo == null || !mVideo.hasVideo() || !mIsMarkAsWatchedButtonEnabled) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.mark_as_watched), optionItem -> {
                    MediaServiceManager.instance().updateHistory(mVideo, mVideo.getDurationMs());
                    mVideo.markFullyViewed();
                    VideoStateService.instance(getContext()).save(new State(mVideo, mVideo.getDurationMs()));
                    Playlist.instance().sync(mVideo);
                    mDialogPresenter.closeDialog();
                }));
    }

    private void appendShareLinkButton() {
        if (!mIsShareLinkButtonEnabled) {
            return;
        }

        AppDialogUtil.appendShareLinkDialogItem(getContext(), mDialogPresenter, mVideo);
    }

    private void appendShareQRLinkButton() {
        if (!mIsShareQRLinkButtonEnabled) {
            return;
        }

        AppDialogUtil.appendShareQRLinkDialogItem(getContext(), mDialogPresenter, mVideo);
    }

    private void appendShareEmbedLinkButton() {
        if (!mIsShareEmbedLinkButtonEnabled) {
            return;
        }

        AppDialogUtil.appendShareEmbedLinkDialogItem(getContext(), mDialogPresenter, mVideo);
    }

    private void appendOpenDescriptionButton() {
        if (!mIsOpenDescriptionButtonEnabled || mVideo == null) {
            return;
        }

        if (mVideo.videoId == null) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.action_video_info),
                        optionItem -> {
                            MessageHelpers.showMessage(getContext(), R.string.wait_data_loading);
                            mServiceManager.loadMetadata(mVideo, metadata -> {
                                String description = metadata.getDescription();
                                if (description != null) {
                                    showLongTextDialog(description);
                                } else {
                                    mServiceManager.loadFormatInfo(mVideo, formatInfo -> {
                                        String newDescription = formatInfo.getDescription();
                                        if (newDescription != null) {
                                            showLongTextDialog(newDescription);
                                        } else {
                                            MessageHelpers.showMessage(getContext(), R.string.description_not_found);
                                        }
                                    });
                                }
                            });
                        }
                ));
    }

    private void appendOpenCommentsButton() {
        if (!mIsOpenCommentsButtonEnabled || mVideo == null) {
            return;
        }

        if (mVideo.videoId == null || mVideo.isLive || mVideo.isUpcoming) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.open_comments),
                        optionItem -> {
                            MessageHelpers.showMessage(getContext(), R.string.wait_data_loading);
                            mServiceManager.loadMetadata(mVideo, metadata -> {
                                CommentsController controller = new CommentsController(getContext(), metadata);
                                controller.onButtonClicked(R.id.action_chat, PlayerUI.BUTTON_ON);
                            });
                        }
                ));
    }

    private void appendPlayVideoButton() {
        if (!mIsPlayVideoButtonEnabled || mVideo == null || mVideo.videoId == null) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.play_video),
                        optionItem -> {
                            PlaybackPresenter.instance(getContext()).openVideo(mVideo);
                            mDialogPresenter.closeDialog();
                        }
                ));
    }

    private void appendPlayVideoIncognitoButton() {
        if (!mIsPlayVideoIncognitoButtonEnabled || mVideo == null || mVideo.videoId == null) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.play_video_incognito),
                        optionItem -> {
                            mVideo.incognito = true;
                            PlaybackPresenter.instance(getContext()).openVideo(mVideo);
                            mDialogPresenter.closeDialog();
                        }
                ));
    }

    private void appendPlayFromStartButton() {
        if (!mIsPlayFromStartButtonEnabled || mVideo == null || mVideo.videoId == null) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.play_from_start),
                        optionItem -> {
                            VideoStateService stateService = VideoStateService.instance(getContext());
                            stateService.save(new State(mVideo, 0));
                            // The saved position isn't enough: a live stream drops it and opens at the live edge,
                            // and the video already in the player saves its own position over it on open.
                            mVideo.pendingPosMs = VideoStateController.START_POSITION_MS;
                            PlaybackPresenter.instance(getContext()).openVideo(mVideo);
                            mDialogPresenter.closeDialog();
                        }
                ));
    }

    private void showLongTextDialog(String description) {
        mDialogPresenter.appendLongTextCategory(mVideo.getTitle(), UiOptionItem.from(description));
        mDialogPresenter.showDialog(mVideo.getTitle());
    }

    private void appendSubscribeButton() {
        if (!mIsSubscribeButtonEnabled) {
            return;
        }

        if (mVideo == null || mVideo.isPlaylistAsChannel() || (!mVideo.isChannel() && !mVideo.hasVideo())) {
            return;
        }

        mVideo.isSubscribed = mVideo.isSubscribed || mVideo.belongsToSubscriptions() || mVideo.belongsToChannelUploads();

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(
                        mVideo.isSynced || mVideo.isSubscribed || (!getSignInService().isSigned() && mVideo.channelId != null) ? mVideo.isSubscribed ?
                                R.string.unsubscribe_from_channel : R.string.subscribe_to_channel : R.string.subscribe_unsubscribe_from_channel),
                        optionItem -> toggleSubscribe()));
    }

    private void appendReturnToBackgroundVideoButton() {
        if (!mIsReturnToBackgroundVideoEnabled || !PlaybackPresenter.instance(getContext()).isRunningInBackground()) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(R.string.return_to_background_video),
                        // Assume that the Playback view already blocked and remembered.
                        optionItem -> getViewManager().startView(PlaybackView.class)
                )
        );
    }

    private void appendAddToPlaybackQueueButton() {
        if (!mIsAddToPlaybackQueueButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.hasVideo()) {
            return;
        }

        Playlist playlist = Playlist.instance();

        // Remain ability to reorder already added video (e.g. move to the top)
        List<Video> all = playlist.getAll();
        if (!all.isEmpty() && mVideo.equals(all.get(all.size() - 1))) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(R.string.add_to_playback_queue),
                        optionItem -> {
                            mVideo.fromQueue = true;
                            playlist.add(mVideo);
                            if (mCallback != null) {
                                mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_ADD_TO_QUEUE);
                            }

                            closeDialog();
                            MessageHelpers.showMessage(getContext(), String.format("%s: %s",
                                    mVideo.getAuthor(),
                                    getContext().getString(R.string.added_to_playback_queue))
                            );
                        }));
    }

    private void appendRemoveFromPlaybackQueueButton() {
        if (!mIsAddToPlaybackQueueButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.hasVideo()) {
            return;
        }

        Playlist playlist = Playlist.instance();

        if (!playlist.contains(mVideo)) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(R.string.remove_from_playback_queue),
                        optionItem -> {
                            mVideo.fromQueue = false;
                            playlist.remove(mVideo);
                            if (mCallback != null) {
                                mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE_FROM_QUEUE);
                            }

                            closeDialog();
                            MessageHelpers.showMessage(getContext(), String.format("%s: %s",
                                    mVideo.getAuthor(),
                                    getContext().getString(R.string.removed_from_playback_queue))
                            );
                        }));
    }

    private void appendPlayNextButton() {
        if (!mIsPlayNextButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.hasVideo()) {
            return;
        }

        Playlist playlist = Playlist.instance();

        if (Helpers.equals(playlist.getNext(), mVideo)) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(R.string.play_next),
                        optionItem -> {
                            mVideo.fromQueue = true;
                            playlist.next(mVideo);
                            if (mCallback != null) {
                                mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_PLAY_NEXT);
                            }

                            closeDialog();
                            MessageHelpers.showMessage(getContext(), String.format("%s: %s",
                                    mVideo.getAuthor(),
                                    getContext().getString(R.string.play_next))
                            );
                        }));
    }

    private void appendShowPlaybackQueueButton() {
        if (!mIsShowPlaybackQueueButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.hasVideo()) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(
                        getContext().getString(R.string.action_playback_queue),
                        optionItem -> AppDialogUtil.showPlaybackQueueDialog(getContext(), video -> PlaybackPresenter.instance(getContext()).openVideo(video))
                )
        );
    }

    private void appendPlaylistOrderButton() {
        if (!mIsPlaylistOrderButtonEnabled) {
            return;
        }

        BrowsePresenter presenter = BrowsePresenter.instance(getContext());

        if (mVideo == null || !(presenter.isPlaylistsSection() && presenter.inForeground())) {
            return;
        }

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(
                        R.string.playlist_order),
                        optionItem -> AppDialogUtil.showPlaylistOrderDialog(getContext(), mVideo, mDialogPresenter::closeDialog)
                ));
    }

    private void appendStreamReminderButton() {
        if (!mIsStreamReminderButtonEnabled) {
            return;
        }

        if (mVideo == null || !mVideo.isUpcoming) {
            return;
        }

        StreamReminderService reminderService = StreamReminderService.instance(getContext());
        boolean reminderSet = reminderService.isReminderSet(mVideo);

        mDialogPresenter.appendSingleButton(
                UiOptionItem.from(getContext().getString(reminderSet ? R.string.unset_stream_reminder : R.string.set_stream_reminder),
                        optionItem -> {
                            reminderService.toggleReminder(mVideo);
                            closeDialog();
                            MessageHelpers.showMessage(getContext(), reminderSet ? R.string.msg_done : R.string.playback_starts_shortly);
                        }
                ));
    }

    private void addRemoveFromPlaylist(String playlistId, String playlistTitle, boolean add) {
        // Not disposed: an edit of another video may still be running
        if (add) {
            Observable<Void> editObserve = mVideo.mediaItem != null ?
                    mMediaItemService.addToPlaylistObserve(playlistId, mVideo.mediaItem) : mMediaItemService.addToPlaylistObserve(playlistId, mVideo.videoId);
            Video video = mVideo;
            // Handle error: Maximum playlist size exceeded (> 5000 items)
            RxHelper.execute(editObserve, error -> MessageHelpers.showLongMessage(getContext(), error.getMessage()),
                    () -> WatchLaterManager.onPlaylistEdited(getContext(), playlistId, video, true));
            mDialogPresenter.closeDialog();
            MessageHelpers.showMessage(getContext(),
                    getContext().getString(R.string.added_to, playlistTitle));
        } else {
            // Check that the current video belongs to the right section
            if (mCallback != null && Helpers.equals(mVideo.playlistId, playlistId)) {
                mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE_FROM_PLAYLIST);
            }
            Observable<Void> editObserve = mMediaItemService.removeFromPlaylistObserve(playlistId, mVideo.videoId);
            Video video = mVideo;
            RxHelper.execute(editObserve,
                    error -> MessageHelpers.showLongMessage(getContext(), error.getMessage()),
                    () -> WatchLaterManager.onPlaylistEdited(getContext(), playlistId, video, false));
            mDialogPresenter.closeDialog();
            MessageHelpers.showMessage(getContext(),
                    getContext().getString(R.string.removed_from, playlistTitle));
        }
    }

    //private void addRemoveFromPlaylist(String playlistId, String playlistTitle, boolean add) {
    //    if (add) {
    //        Observable<Void> editObserve = mItemManager.addToPlaylistObserve(playlistId, mVideo.videoId);
    //        mAddToPlaylistAction = RxUtils.execute(editObserve);
    //        mDialogPresenter.closeDialog();
    //        MessageHelpers.showMessage(getContext(),
    //                getContext().getString(R.string.added_to, playlistTitle));
    //    } else {
    //        AppDialogUtil.showConfirmationDialog(getContext(), () -> {
    //            // Check that the current video belongs to the right section
    //            if (mCallback != null && Helpers.equals(mVideo.playlistId, playlistId)) {
    //                mCallback.onItemAction(mVideo, VideoMenuCallback.ACTION_REMOVE_FROM_PLAYLIST);
    //            }
    //            Observable<Void> editObserve = mItemManager.removeFromPlaylistObserve(playlistId, mVideo.videoId);
    //            mAddToPlaylistAction = RxUtils.execute(editObserve);
    //            mDialogPresenter.closeDialog();
    //            MessageHelpers.showMessage(getContext(),
    //                    getContext().getString(R.string.removed_from, playlistTitle));
    //        }, getContext().getString(R.string.dialog_remove_from, playlistTitle));
    //    }
    //}

    private void toggleSubscribe() {
        if (mVideo == null) {
            return;
        }

        //mVideo.isSynced = true; // default to subscribe

        // Until synced we won't really know weather we subscribed to a channel.
        // Exclusion: channel item (can't be synced)
        // Note, regular items (from subscribed section etc) aren't contain channel id
        if (mVideo.isSynced || mVideo.isSubscribed || mVideo.isChannel() || (!getSignInService().isSigned() && mVideo.channelId != null)) {
            toggleSubscribe(mVideo);
        } else {
            MessageHelpers.showMessage(getContext(), R.string.wait_data_loading);

            mServiceManager.loadMetadata(mVideo, metadata -> {
                mVideo.sync(metadata);
                toggleSubscribe(mVideo);
            });
        }
    }

    private void toggleSubscribe(Video video) {
        if (video == null) {
            return;
        }

        RxHelper.disposeActions(mSubscribeAction);

        Observable<Void> observable = video.isSubscribed ?
                mMediaItemService.unsubscribeObserve(video.channelId) : mMediaItemService.subscribeObserve(video.channelId);

        mSubscribeAction = RxHelper.execute(observable);

        video.isSubscribed = !video.isSubscribed;

        if (!video.isSubscribed && mCallback != null) {
            mCallback.onItemAction(video, VideoMenuCallback.ACTION_UNSUBSCRIBE);
        }

        MessageHelpers.showMessage(getContext(), getContext().getString(!video.isSubscribed ? R.string.unsubscribed_from_channel : R.string.subscribed_to_channel));
    }

    @Override
    protected void updateEnabledMenuItems() {
        super.updateEnabledMenuItems();

        MainUIData mainUIData = MainUIData.instance(getContext());

        mIsOpenChannelUploadsButtonEnabled = true;
        mIsOpenPlaylistButtonEnabled = true;
        mIsReturnToBackgroundVideoEnabled = true;
        mIsOpenChannelButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_OPEN_CHANNEL);
        mIsAddToRecentPlaylistButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_RECENT_PLAYLIST);
        mIsAddToPlaybackQueueButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_ADD_TO_QUEUE);
        mIsPlayNextButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_PLAY_NEXT);
        mIsAddToWatchLaterButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_ADD_TO_WATCH_LATER);
        mIsLikeButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_LIKE);
        mIsAddToPlaylistButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_ADD_TO_PLAYLIST);
        mIsShareLinkButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_SHARE_LINK);
        mIsShareQRLinkButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_SHARE_QR_LINK);
        mIsShareEmbedLinkButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_SHARE_EMBED_LINK);
        mIsNotInterestedButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_NOT_INTERESTED);
        mIsNotRecommendChannelEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_NOT_RECOMMEND_CHANNEL);
        mIsBlockChannelEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_BLOCK_CHANNEL);
        mIsReportAiChannelEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_REPORT_AI_CHANNEL);
        mIsHideKeywordsEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_HIDE_KEYWORDS);
        mIsExcludeChannelFromHidingEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_EXCLUDE_CHANNEL_FROM_HIDING);
        mIsRemoveFromHistoryButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_REMOVE_FROM_HISTORY);
        mIsHideButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_HIDE);
        mIsOpenDescriptionButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_OPEN_DESCRIPTION);
        mIsPlayVideoButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_PLAY_VIDEO);
        mIsPlayVideoIncognitoButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_PLAY_VIDEO_INCOGNITO);
        mIsPlayFromStartButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_PLAY_FROM_START);
        mIsSubscribeButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_SUBSCRIBE);
        mIsStreamReminderButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_STREAM_REMINDER);
        mIsShowPlaybackQueueButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_SHOW_QUEUE);
        mIsPlaylistOrderButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_PLAYLIST_ORDER);
        mIsMarkAsWatchedButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_MARK_AS_WATCHED);
        mIsOpenCommentsButtonEnabled = mainUIData.isMenuItemEnabled(mMenu, MainUIData.MENU_ITEM_OPEN_COMMENTS);
    }

    private void initMenuMapping() {
        mMenuMapping.clear();

        mMenuMapping.put(MainUIData.MENU_ITEM_PLAY_VIDEO, new MenuAction(this::appendPlayVideoButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_PLAY_VIDEO_INCOGNITO, new MenuAction(this::appendPlayVideoIncognitoButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_PLAY_FROM_START, new MenuAction(this::appendPlayFromStartButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_REMOVE_FROM_HISTORY, new MenuAction(this::appendRemoveFromHistoryButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_STREAM_REMINDER, new MenuAction(this::appendStreamReminderButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_RECENT_PLAYLIST, new MenuAction(this::appendAddToRecentPlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_ADD_TO_WATCH_LATER, new MenuAction(this::appendAddToWatchLaterButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_LIKE, new MenuAction(this::appendLikeButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_ADD_TO_PLAYLIST, new MenuAction(this::appendAddToPlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_CREATE_PLAYLIST, new MenuAction(this::appendCreatePlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_CREATE_LOCAL_PLAYLIST, new MenuAction(this::appendCreateLocalPlaylistButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_RENAME_PLAYLIST, new MenuAction(this::appendRenamePlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_COPY_PLAYLIST_TO_YOUTUBE, new MenuAction(this::appendCopyPlaylistToYouTubeButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_ADD_TO_NEW_PLAYLIST, new MenuAction(this::appendAddToNewPlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_NOT_INTERESTED, new MenuAction(this::appendNotInterestedButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_NOT_RECOMMEND_CHANNEL, new MenuAction(this::appendNotRecommendChannelButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_HIDE, new MenuAction(this::appendHideButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_BLOCK_CHANNEL, new MenuAction(this::appendBlockChannelButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_REPORT_AI_CHANNEL, new MenuAction(this::appendReportAiChannelButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_HIDE_KEYWORDS, new MenuAction(this::appendHideKeywordsButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_EXCLUDE_CHANNEL_FROM_HIDING, new MenuAction(this::appendExcludeChannelFromHidingButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_MARK_AS_WATCHED, new MenuAction(this::appendMarkAsWatchedButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_PLAYLIST_ORDER, new MenuAction(this::appendPlaylistOrderButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_ADD_TO_QUEUE, new MenuAction(() -> { appendAddToPlaybackQueueButton(); appendRemoveFromPlaybackQueueButton(); }, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_PLAY_NEXT, new MenuAction(this::appendPlayNextButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SHOW_QUEUE, new MenuAction(this::appendShowPlaybackQueueButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_OPEN_CHANNEL, new MenuAction(this::appendOpenChannelButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_OPEN_PLAYLIST, new MenuAction(this::appendOpenPlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SUBSCRIBE, new MenuAction(this::appendSubscribeButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_EXCLUDE_FROM_CONTENT_BLOCK, new MenuAction(this::appendToggleExcludeFromContentBlockButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_PIN_TO_SIDEBAR, new MenuAction(this::appendTogglePinVideoToSidebarButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_ADD_TO_HOME_ROWS, new MenuAction(this::appendToggleHomeRowButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_ADD_TO_HOME_SCREEN, new MenuAction(this::appendToggleHomeScreenPlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SAVE_REMOVE_PLAYLIST, new MenuAction(this::appendSaveRemovePlaylistButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_OPEN_DESCRIPTION, new MenuAction(this::appendOpenDescriptionButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SHARE_LINK, new MenuAction(this::appendShareLinkButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SHARE_QR_LINK, new MenuAction(this::appendShareQRLinkButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SHARE_EMBED_LINK, new MenuAction(this::appendShareEmbedLinkButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_SELECT_ACCOUNT, new MenuAction(this::appendAccountSelectionButton, false));
        mMenuMapping.put(MainUIData.MENU_ITEM_TOGGLE_HISTORY, new MenuAction(this::appendToggleHistoryButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_CLEAR_HISTORY, new MenuAction(this::appendClearHistoryButton, true));
        mMenuMapping.put(MainUIData.MENU_ITEM_OPEN_COMMENTS, new MenuAction(this::appendOpenCommentsButton, false));

        for (ContextMenuProvider provider : new ContextMenuManager(getContext()).getProviders()) {
            if (provider.getMenuType() != ContextMenuProvider.MENU_TYPE_VIDEO) {
                continue;
            }
            mMenuMapping.put(provider.getId(), new MenuAction(() -> appendContextMenuItem(provider), false));
        }
    }

    private void appendContextMenuItem(ContextMenuProvider provider) {
        MainUIData mainUIData = MainUIData.instance(getContext());
        if (mainUIData.isMenuItemEnabled(mMenu, provider.getId()) && provider.isEnabled(getVideo())) {
            mDialogPresenter.appendSingleButton(
                    UiOptionItem.from(getContext().getString(provider.getTitleResId()), optionItem -> provider.onClicked(getVideo(), getCallback()))
            );
        }
    }
}
