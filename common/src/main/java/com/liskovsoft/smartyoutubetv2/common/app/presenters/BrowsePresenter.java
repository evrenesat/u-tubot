package com.liskovsoft.smartyoutubetv2.common.app.presenters;

import android.annotation.SuppressLint;
import android.content.Context;
import android.text.TextUtils;
import android.util.Pair;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.oauth.Account;
import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.ItemGroup;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.locale.LocaleUtility;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Playlist;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SimpleMediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.CategoryEmptyError;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.ErrorFragmentData;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.PasswordError;
import com.liskovsoft.smartyoutubetv2.common.app.models.errors.SignInError;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService.State;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.VideoActionPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.ChannelUploadsMenuPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.SectionMenuPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.VideoMenuPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.VideoMenuPresenter.VideoMenuCallback;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.providers.channelgroup.ChannelGroupServiceWrapper;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.interfaces.SectionPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.interfaces.VideoGroupPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.service.GroupReferences;
import com.liskovsoft.smartyoutubetv2.common.app.views.BrowseView;
import com.liskovsoft.smartyoutubetv2.common.misc.AppDataSourceManager;
import com.liskovsoft.smartyoutubetv2.common.misc.BrowseProcessorManager;
import com.liskovsoft.smartyoutubetv2.common.misc.DuplicateFilter;
import com.liskovsoft.smartyoutubetv2.common.misc.HiddenVideoResolver;
import com.liskovsoft.smartyoutubetv2.common.misc.HomeRowOrderer;
import com.liskovsoft.smartyoutubetv2.common.misc.MediaServiceManager;
import com.liskovsoft.smartyoutubetv2.common.misc.MediaServiceManager.AccountChangeListener;
import com.liskovsoft.smartyoutubetv2.common.misc.Skins;
import com.liskovsoft.smartyoutubetv2.common.prefs.AccountsData;
import com.liskovsoft.smartyoutubetv2.common.misc.AiSListManager;
import com.liskovsoft.smartyoutubetv2.common.misc.VideoCategoryManager;
import com.liskovsoft.smartyoutubetv2.common.misc.WatchLaterManager;
import com.liskovsoft.smartyoutubetv2.common.prefs.BlockedChannelData;
import com.liskovsoft.smartyoutubetv2.common.prefs.DuplicatesData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HiddenVideosData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HomeRowsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HomeRowsData.Row;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.prefs.SectionFilterData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotBrowseCache;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotInboxOpen;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotInboxSection;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotProcessedOpen;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotProcessedSection;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSectionError;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.youtubeapi.service.internal.MediaServiceData;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Map.Entry;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicInteger;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;

public class BrowsePresenter extends BasePresenter<BrowseView> implements SectionPresenter, VideoGroupPresenter, AccountChangeListener {
    private static final String TAG = BrowsePresenter.class.getSimpleName();
    // A row whose next pages have only videos the rows above have (see DuplicateFilter) stops looking after these
    private static final int MAX_DUPLICATE_PAGES = 5;
    /**
     * How often the Inbox's unread badge re-checks the backend while the browse UI is up: enough to show a result that became ready
     * after the viewer left the Inbox, without a network call on every rail move. Package-private so a test can force a check.
     */
    static final long INBOX_BADGE_REFRESH_MS = 5_000;
    @SuppressLint("StaticFieldLeak")
    private static BrowsePresenter sInstance;
    private final List<BrowseSection> mSections;
    private final List<BrowseSection> mErrorSections;
    private final Map<Integer, Observable<MediaGroup>> mGridMapping;
    private final Map<Integer, Observable<List<MediaGroup>>> mRowMapping;
    private final Map<Integer, Callable<List<SettingsItem>>> mSettingsGridMapping;
    private final Map<Integer, Callable<List<Video>>> mLocalGridMappings;
    private final Map<Integer, Observable<ProcessedList>> mProcessedMapping;
    private final Map<Integer, Observable<InboxList>> mInboxMapping;
    private final Map<Integer, BrowseSection> mSectionsMapping;
    private final AppDataSourceManager mDataSourcePresenter;
    private final BrowseProcessorManager mBrowseProcessor;
    private final List<Disposable> mActions;
    // The rows added to Home in its last load: they're not YouTube's (see HomeRowsData, cleared as Home loads)
    private final Map<MediaGroup, Row> mAddedHomeRows = Collections.synchronizedMap(new IdentityHashMap<>());
    // The rows of channels of the last load of Home, with the channel: their cards don't name it (see findAddedHomeRowChannelId)
    private final Map<VideoGroup, String> mAddedHomeRowChannelIds = Collections.synchronizedMap(new IdentityHashMap<>());
    private final Runnable mRefreshSection = this::refresh;
    private final Runnable mUpdateSections = this::updateSections;
    private final Runnable mReplayCachedGroups = this::replayCachedGroups;
    private final UtubotBrowseCache mBrowseCache;
    /** The u-tubot connection listener, registered while the Processed section's cache is live: removed when unheld (see unhold) */
    private Runnable mConnectionListener;
    /**
     * The section shows the videos of one of its channels: a load error doesn't reload the whole section, in a skin that keeps
     * it (see SkinTraits)
     */
    private boolean mIsChannelContent;
    private BrowseSection mCurrentSection;
    private Video mCurrentVideo;
    private long mLastUpdateTimeMs = -1;
    /** The caller's unread inbox count, last known from the backend: the Inbox rail's badge while the Inbox is not open */
    private int mInboxUnread;
    /** When the inbox unread badge last re-checked the backend, to avoid a call on every rail move (see INBOX_BADGE_REFRESH_MS) */
    private long mInboxBadgeLastRefreshMs;
    /** The inbox unread badge's refresh, tracked apart from the section loads (disposeActions would drop it): disposed before re-subscribing */
    private Disposable mInboxBadgeAction;
    private int mBootSectionIndex;
    private int mBootstrapSectionId = -1;
    private Locale mSectionsLocale;
    private boolean mCachedContentShown;
    private List<VideoGroup> mCachedShownGroups;
    private BrowseSection mCachedReplaySection;
    private List<VideoGroup> mCachedReplayGroups;
    /**
     * A background load of a section whose cached cards are on screen: the multi-grid's uploads are loaded from the network too,
     * while a fresh cache replay keeps them (see onVideoItemSelected).
     */
    private boolean mCachedRefreshStarted;
    // The next channel selection of a cached multi-grid is the view's auto-selection, whose uploads are already shown
    private boolean mSkipCachedUploadsSelection;
    /**
     * Cards removed while a cached refresh is still loading: the load's groups still carry them, so its saves filter them out.
     */
    private final Map<Integer, Set<String>> mRemovedCardsBySection = new HashMap<>();
    /**
     * Sections whose cache was dropped while a cached refresh is still loading: the refresh must not write its groups back.
     */
    private final Set<Integer> mInvalidatedCachedSections = new HashSet<>();

    private BrowsePresenter(Context context) {
        super(context);
        mDataSourcePresenter = AppDataSourceManager.instance();
        mSections = new ArrayList<>();
        mErrorSections = new ArrayList<>();
        mGridMapping = new HashMap<>();
        mRowMapping = new HashMap<>();
        mSettingsGridMapping = new HashMap<>();
        mLocalGridMappings = new HashMap<>();
        mProcessedMapping = new HashMap<>();
        mInboxMapping = new HashMap<>();
        mSectionsMapping = new HashMap<>();
        MediaServiceManager.instance().addAccountListener(this);

        mBrowseProcessor = new BrowseProcessorManager(getContext(), this::syncItem);
        mActions = new ArrayList<>();
        mBrowseCache = UtubotSettings.isBuiltIn() ? UtubotBrowseCache.instance(context) : null;
        if (mBrowseCache != null) {
            // The Processed section's cards come from the backend: another backend or token makes them another user's (see onUtubotConnectionChanged)
            mConnectionListener = this::onUtubotConnectionChanged;
            UtubotSettings.instance(context).addConnectionListener(mConnectionListener);
        }
        WatchLaterManager.instance(context).setOnEdited(this::onWatchLaterEdited);
        initSectionMappings();
        // Read above: the Home rows and the pinned items refer to the groups by the ids they have now, before the sections are made
        GroupReferences.instance(context).update();
        updateChannelSorting();
        updatePlaylistsStyle();
    }

    public static BrowsePresenter instance(Context context) {
        if (sInstance == null) {
            sInstance = new BrowsePresenter(context);
        }

        sInstance.setContext(context);

        return sInstance;
    }

    public static void unhold() {
        if (sInstance != null && sInstance.mConnectionListener != null) {
            UtubotSettings.instance(sInstance.getContext()).removeConnectionListener(sInstance.mConnectionListener);
        }
        sInstance = null;
    }

    @Override
    public void onViewInitialized() {
        super.onViewInitialized();

        if (getView() == null) {
            return;
        }

        // Recreated in another language or country, another account's (see LocaleData): the titles are in the old one
        if (!Helpers.equals(LocaleUtility.getCurrentLocale(getContext()), mSectionsLocale)) {
            // An in-flight cached refresh would save the old locale's rows after the cache is cleared
            disposeActions();

            if (mBrowseCache != null) {
                mBrowseCache.invalidate();
            }
            initSectionMappings();
            updateChannelSorting();
            updatePlaylistsStyle();
        }

        updateSections();

        // Move default focus
        int selectedSectionIndex = findSectionIndex(mCurrentSection != null ? mCurrentSection.getId() : mBootstrapSectionId);
        mBootstrapSectionId = -1;
        getView().selectSection(selectedSectionIndex != -1 ? selectedSectionIndex : mBootSectionIndex, true);
    }

    @Override
    public void onViewPaused() {
        super.onViewPaused();

        saveSelectedItems();
    }

    @Override
    public void onViewResumed() {
        super.onViewResumed();

        // The browse UI is back (the player just closed, the app returned to the foreground): a result that became ready while
        // watching shows on the Inbox rail's badge, so the badge is fresh without opening the Inbox
        refreshInboxBadge();
        refreshIfNeeded();
        MediaServiceManager.instance().warmUpPlaybackIfExpired();
    }

    private void refreshIfNeeded() {
        if (getView() == null) {
            return;
        }

        if (mBrowseCache != null) {
            if (mCurrentSection != null && browseCacheState(mCurrentSection) == UtubotBrowseCache.State.STALE) {
                refreshFromCache(mCurrentSection);
            }
            return;
        }

        if (!isHomeSection() || mLastUpdateTimeMs == -1 || System.currentTimeMillis() - mLastUpdateTimeMs < 3 * 60 * 60 * 1_000) {
            return;
        }

        Utils.testUrl("https://www.youtube.com", () -> refresh(false));
    }

    private void saveSelectedItems() {
        // Fix position reset when jumping between sections
        if (mCurrentVideo != null && mCurrentVideo.getPositionInsideGroup() == 0 && (System.currentTimeMillis() - mCurrentVideo.timestamp) < 10_000) {
            return;
        }

        if ((isSubscriptionsSection() && getGeneralData().isRememberSubscriptionsPositionEnabled()) ||
                (isPinnedSection() && getGeneralData().isRememberPinnedPositionEnabled())) {
            getGeneralData().setSelectedItem(mCurrentSection.getId(), mCurrentVideo);
        }
    }

    private void restoreSelectedItems() {
        if (getView() == null) {
            return;
        }

        if ((isSubscriptionsSection() && getGeneralData().isRememberSubscriptionsPositionEnabled()) ||
                (isPinnedSection() && getGeneralData().isRememberPinnedPositionEnabled())) {
            getView().selectSectionItem(getGeneralData().getSelectedItem(mCurrentSection.getId()));
        }
    }

    private void initSectionMappings() {
        mSectionsLocale = LocaleUtility.getCurrentLocale(getContext());

        initSectionMapping();

        initRowAndGridMapping();

        initSettingsGridMapping();
        initLocalGridMapping();
        initProcessedMapping();
        initInboxMapping();
    }

    /**
     * The u-tubot Processed section is the built-in flavor's only (u-tubot #66); its content comes from the backend, not YouTube
     */
    private void initProcessedMapping() {
        if (UtubotSettings.isBuiltIn()) {
            mProcessedMapping.put(UtubotProcessedSection.ID,
                    UtubotManager.instance(getContext()).processedObserve(UtubotProcessedSection.LIMIT));
        }
    }

    /**
     * The u-tubot Inbox section (u-tubot #160): one tile per ready result, its content comes from the backend, not YouTube
     */
    private void initInboxMapping() {
        if (UtubotSettings.isBuiltIn()) {
            mInboxMapping.put(UtubotInboxSection.ID,
                    UtubotManager.instance(getContext()).inboxObserve(UtubotInboxSection.LIMIT));
        }
    }

    private void initSectionMapping() {
        String country = LocaleUtility.getCurrentLocale(getContext()).getCountry();
        int uploadsType = getMainUIData().isUploadsOldLookEnabled() ? BrowseSection.TYPE_GRID : BrowseSection.TYPE_MULTI_GRID;

        mSectionsMapping.put(MediaGroup.TYPE_HOME, new BrowseSection(MediaGroup.TYPE_HOME, getContext().getString(R.string.header_home), BrowseSection.TYPE_ROW, R.drawable.icon_home, false));
        mSectionsMapping.put(MediaGroup.TYPE_SHORTS, new BrowseSection(MediaGroup.TYPE_SHORTS, getContext().getString(R.string.header_shorts), BrowseSection.TYPE_SHORTS_GRID, R.drawable.icon_shorts));
        mSectionsMapping.put(MediaGroup.TYPE_KIDS_HOME, new BrowseSection(MediaGroup.TYPE_KIDS_HOME, getContext().getString(R.string.header_kids_home), BrowseSection.TYPE_ROW, R.drawable.icon_kids_home));
        mSectionsMapping.put(MediaGroup.TYPE_SPORTS, new BrowseSection(MediaGroup.TYPE_SPORTS, getContext().getString(R.string.header_sports), BrowseSection.TYPE_ROW, R.drawable.icon_sports));
        mSectionsMapping.put(MediaGroup.TYPE_LIVE, new BrowseSection(MediaGroup.TYPE_LIVE, getContext().getString(R.string.badge_live), BrowseSection.TYPE_ROW, R.drawable.icon_live));
        mSectionsMapping.put(MediaGroup.TYPE_MY_VIDEOS, new BrowseSection(MediaGroup.TYPE_MY_VIDEOS, getContext().getString(R.string.my_videos), BrowseSection.TYPE_ROW, R.drawable.icon_playlist));
        mSectionsMapping.put(MediaGroup.TYPE_GAMING, new BrowseSection(MediaGroup.TYPE_GAMING, getContext().getString(R.string.header_gaming), BrowseSection.TYPE_ROW, R.drawable.icon_gaming));
        if (!Helpers.equalsAny(country, "RU", "BY")) {
            mSectionsMapping.put(MediaGroup.TYPE_NEWS, new BrowseSection(MediaGroup.TYPE_NEWS, getContext().getString(R.string.header_news), BrowseSection.TYPE_ROW, R.drawable.icon_news));
        }
        mSectionsMapping.put(MediaGroup.TYPE_MUSIC, new BrowseSection(MediaGroup.TYPE_MUSIC, getContext().getString(R.string.header_music), BrowseSection.TYPE_ROW, R.drawable.icon_music));
        mSectionsMapping.put(MediaGroup.TYPE_CHANNEL_UPLOADS, new BrowseSection(MediaGroup.TYPE_CHANNEL_UPLOADS, getContext().getString(R.string.header_channels), uploadsType, R.drawable.icon_channels, false));
        mSectionsMapping.put(MediaGroup.TYPE_SUBSCRIPTIONS, new BrowseSection(MediaGroup.TYPE_SUBSCRIPTIONS, getContext().getString(R.string.header_subscriptions), BrowseSection.TYPE_GRID, R.drawable.icon_subscriptions, false));
        mSectionsMapping.put(MediaGroup.TYPE_HISTORY, new BrowseSection(MediaGroup.TYPE_HISTORY, getContext().getString(R.string.header_history), getHistoryType(), R.drawable.icon_history, true));
        mSectionsMapping.put(MediaGroup.TYPE_WATCH_LATER, new BrowseSection(MediaGroup.TYPE_WATCH_LATER, getContext().getString(R.string.watch_later), BrowseSection.TYPE_GRID, R.drawable.icon_watch_later, true));
        mSectionsMapping.put(MediaGroup.TYPE_BLOCKED_CHANNELS,
                new BrowseSection(MediaGroup.TYPE_BLOCKED_CHANNELS, getContext().getString(R.string.header_blocked_channels), BrowseSection.TYPE_GRID, R.drawable.icon_blocked_channels, false));
        BrowseSection blockedAiChannels =
                new BrowseSection(MediaGroup.TYPE_BLOCKED_AI_CHANNELS, getContext().getString(R.string.header_blocked_ai_channels), BrowseSection.TYPE_GRID, R.drawable.icon_blocked_channels, false);
        // Easily taken for the whole AiSList
        blockedAiChannels.setMessage(getContext().getString(R.string.blocked_ai_channels_message));
        mSectionsMapping.put(MediaGroup.TYPE_BLOCKED_AI_CHANNELS, blockedAiChannels);
        mSectionsMapping.put(MediaGroup.TYPE_HIDDEN_VIDEOS,
                new BrowseSection(MediaGroup.TYPE_HIDDEN_VIDEOS, getContext().getString(R.string.unhide), BrowseSection.TYPE_ROW, R.drawable.icon_unhide, false));
        mSectionsMapping.put(MediaGroup.TYPE_USER_PLAYLISTS, new BrowseSection(MediaGroup.TYPE_USER_PLAYLISTS, getContext().getString(R.string.header_playlists), BrowseSection.TYPE_ROW, R.drawable.icon_playlist, false));
        mSectionsMapping.put(MediaGroup.TYPE_NOTIFICATIONS, new BrowseSection(MediaGroup.TYPE_NOTIFICATIONS, getContext().getString(R.string.header_notifications), BrowseSection.TYPE_GRID, R.drawable.icon_notification, false));
        mSectionsMapping.put(MediaGroup.TYPE_PLAYBACK_QUEUE, new BrowseSection(MediaGroup.TYPE_PLAYBACK_QUEUE, getContext().getString(R.string.playback_queue_category_title), BrowseSection.TYPE_GRID, R.drawable.icon_queue, false));

         // Past the built-in entries. The flavor has the u-tubot layer built in: the section comes from the backend, not YouTube
         if (UtubotSettings.isBuiltIn()) {
             BrowseSection processed = new BrowseSection(UtubotProcessedSection.ID,
                     getContext().getString(R.string.utubot_processed_title), BrowseSection.TYPE_GRID, R.drawable.icon_playlist);
             processed.setMessage(getContext().getString(R.string.utubot_processed_message));
             mSectionsMapping.put(UtubotProcessedSection.ID, processed);

             BrowseSection inbox = new BrowseSection(UtubotInboxSection.ID,
                     getContext().getString(R.string.utubot_inbox_title), BrowseSection.TYPE_GRID, R.drawable.icon_playlist);
             inbox.setMessage(getContext().getString(R.string.utubot_inbox_message));
             mSectionsMapping.put(UtubotInboxSection.ID, inbox);
         }

        if (getSidebarService().isSettingsSectionEnabled()) {
            mSectionsMapping.put(MediaGroup.TYPE_SETTINGS, new BrowseSection(MediaGroup.TYPE_SETTINGS, getContext().getString(R.string.header_settings), BrowseSection.TYPE_SETTINGS_GRID, R.drawable.icon_settings));
        }
    }

    private void initRowAndGridMapping() {
        mRowMapping.put(MediaGroup.TYPE_HOME, createHomeObserve());
        mRowMapping.put(MediaGroup.TYPE_KIDS_HOME, getContentService().getKidsHomeObserve());
        mRowMapping.put(MediaGroup.TYPE_SPORTS, getContentService().getSportsObserve());
        mRowMapping.put(MediaGroup.TYPE_LIVE, getContentService().getLiveObserve());
        mRowMapping.put(MediaGroup.TYPE_NEWS, getContentService().getNewsObserve());
        mRowMapping.put(MediaGroup.TYPE_MUSIC, getContentService().getMusicObserve());
        mRowMapping.put(MediaGroup.TYPE_GAMING, getContentService().getGamingObserve());
        mRowMapping.put(MediaGroup.TYPE_USER_PLAYLISTS, getContentService().getPlaylistRowsObserve());
        mRowMapping.put(MediaGroup.TYPE_MY_VIDEOS, getContentService().getMyVideosObserve());
        mRowMapping.put(MediaGroup.TYPE_HISTORY, getContentService().getHistoryRowsObserve());

        mGridMapping.put(MediaGroup.TYPE_SHORTS, getContentService().getShortsObserve());
        mGridMapping.put(MediaGroup.TYPE_SUBSCRIPTIONS, getContentService().getSubscriptionsObserve());
        mGridMapping.put(MediaGroup.TYPE_HISTORY, getContentService().getHistoryVideosObserve());
        mGridMapping.put(MediaGroup.TYPE_WATCH_LATER, getContentService().getWatchLaterObserve());
        mGridMapping.put(MediaGroup.TYPE_CHANNEL_UPLOADS, getContentService().getSubscribedChannelsByNewContentObserve());
        mGridMapping.put(MediaGroup.TYPE_NOTIFICATIONS, getNotificationsService().getNotificationItemsObserve());
    }

    /**
     * YouTube's rows of Home and the rows added to it, in the order of HomeRowsData. Read at each load.
     * As YouTube sends them while that's YouTube's order and nothing is added.
     */
    private Observable<List<MediaGroup>> createHomeObserve() {
        Observable<List<MediaGroup>> youTubeRows = getContentService().getHomeObserve();
        HomeRowsData homeRowsData = HomeRowsData.instance(getContext());

        return Observable.defer(() -> {
            if (homeRowsData.isDefault()) {
                return youTubeRows;
            }

            return HomeRowOrderer.order(homeRowsData.getHiddenKinds(), homeRowsData.getRows(), youTubeRows,
                    row -> createAddedHomeRowObserve(row).doOnNext(group -> mAddedHomeRows.put(group, row)));
        });
    }

    private Observable<MediaGroup> createAddedHomeRowObserve(Row row) {
        if (row.type == Row.TYPE_SUBSCRIPTIONS) {
            return getContentService().getSubscriptionsObserve();
        }

        // The uploads of its channels, as the grid of the group in the sidebar. Nothing when the group's gone.
        if (row.type == Row.TYPE_CHANNEL_GROUP) {
            return getContentService().getChannelFeedObserve(ChannelGroupServiceWrapper.instance(getContext()).findChannelIdsForGroup(row.channelGroupId));
        }

        // Its uploads, as the grid of the channel
        Video channel = new Video();
        channel.channelId = row.channelId;
        channel.title = row.title;

        return getContentService().getGroupObserve(SimpleMediaItem.from(channel));
    }

    private void initPinnedSections() {
        mSections.clear();

        Collection<Video> pinnedItems = getSidebarService().getPinnedItems();

        for (Video item : pinnedItems) {
            if (item != null) {
                if (item.sectionId == -1) { // pinned channel or playlist
                    BrowseSection section = createPinnedSection(item);
                    mSections.add(section);
                } else {
                    BrowseSection section = mSectionsMapping.get(item.sectionId);

                    if (section != null) {
                        mSections.add(section);
                    }
                }
            }
        }

        // Child mode: Channels, then Subscriptions first. Settings is last (see SidebarService.keepSettingsLast).
        if (getGeneralData().isChildModeEnabled()) {
            moveSection(MediaGroup.TYPE_SUBSCRIPTIONS);
            moveSection(MediaGroup.TYPE_CHANNEL_UPLOADS);
        }
    }

    /**
     * To the top of the sidebar, when it's shown
     */
    private void moveSection(int sectionId) {
        BrowseSection section = Helpers.findFirst(mSections, item -> item.getId() == sectionId);

        if (section != null) {
            mSections.remove(section);
            mSections.add(0, section);
        }
    }

    private void initPinnedCallbacks() {
        Collection<Video> pinnedItems = getSidebarService().getPinnedItems();

        for (Video item : pinnedItems) {
            if (item != null && item.sectionId == -1) {
                createPinnedMapping(item);
            }
        }
    }

    private void initSettingsGridMapping() {
        mSettingsGridMapping.put(MediaGroup.TYPE_SETTINGS, () -> mDataSourcePresenter.getSettingItems(getContext()));
    }

    private void initLocalGridMapping() {
        mLocalGridMappings.put(MediaGroup.TYPE_PLAYBACK_QUEUE, () -> Playlist.instance().getAllReversed());
        mLocalGridMappings.put(MediaGroup.TYPE_BLOCKED_CHANNELS, this::getBlockedChannels);
        mLocalGridMappings.put(MediaGroup.TYPE_BLOCKED_AI_CHANNELS, () -> AiSListManager.instance(getContext()).getBlockedChannels());
    }

    private List<Video> getBlockedChannels() {
        BlockedChannelData blockedChannelData = BlockedChannelData.instance(getContext());
        List<Video> videos = new ArrayList<>();

        for (Pair<String, String> entry : blockedChannelData.getChannelIdsWithNames()) {
            Video video = new Video();
            video.channelId = entry.first;
            video.title = entry.second;
            videos.add(video);
        }

        return videos;
    }

    public void updateSections() {
        if (getView() == null) {
            return;
        }

        initPinnedData();

        refreshSections();
    }

    private void refreshSections() {
        if (getView() == null) {
            return;
        }

        // clean up (profile changed etc)
        getView().removeAllSections();

        int bootSectionId = getSidebarService().getBootSectionId();

        // Empty Home on first run fix. Switch to something non-empty.
        if (!getSignInService().isSigned() && VideoStateService.instance(getContext()).isEmpty()) {
            bootSectionId = MediaGroup.TYPE_MUSIC;
        }

        int index = 0;

        for (BrowseSection section : mErrorSections) {
            getView().addSection(index++, section);
        }

        // The top of the sidebar, past the error sections: First section, or the boot section isn't in the sidebar
        mBootSectionIndex = index;

        for (BrowseSection section : mSections) { // contains sections and pinned items!
            if (section.getId() == MediaGroup.TYPE_SETTINGS) {
                section.setEnabled(true);
            }

            if (section.isEnabled()) {
                if (section.getId() == bootSectionId) {
                    mBootSectionIndex = index;
                }
                getView().addSection(index++, section);
            } else {
                getView().removeSection(section);
            }
        }

        // Refresh and restore last focus
        int selectedSectionIndex = findSectionIndex(mCurrentSection != null ? mCurrentSection.getId() : -1);
        getView().selectSection(selectedSectionIndex != -1 ? selectedSectionIndex : mBootSectionIndex, false);
    }

    private void initPinnedData() {
        initPinnedSections();
        initPinnedCallbacks();
        initPasswordSection();
    }

    private void sortSections() {
        // NOTE: Comparator.comparingInt API >= 24
        Collections.sort(mSections, (o1, o2) -> {
            return getSidebarService().getSectionIndex(o1.getId()) - getSidebarService().getSectionIndex(o2.getId());
        });
    }

    public void updateChannelSorting() {
        int sortingType = getMainUIData().getChannelCategorySorting();

        switch (sortingType) {
            case MainUIData.CHANNEL_SORTING_DEFAULT:
                mGridMapping.put(MediaGroup.TYPE_CHANNEL_UPLOADS, getContentService().getSubscribedChannelsObserve());
                break;
            case MainUIData.CHANNEL_SORTING_NAME2:
            case MainUIData.CHANNEL_SORTING_NAME:
                mGridMapping.put(MediaGroup.TYPE_CHANNEL_UPLOADS, getContentService().getSubscribedChannelsByNameObserve());
                break;
            case MainUIData.CHANNEL_SORTING_NEW_CONTENT:
                mGridMapping.put(MediaGroup.TYPE_CHANNEL_UPLOADS, getContentService().getSubscribedChannelsByNewContentObserve());
                break;
            case MainUIData.CHANNEL_SORTING_LAST_VIEWED:
                mGridMapping.put(MediaGroup.TYPE_CHANNEL_UPLOADS, getContentService().getSubscribedChannelsByLastViewedObserve());
                break;
        }
    }

    public void updatePlaylistsStyle() {
        int playlistsStyle = getMainUIData().getPlaylistsStyle();

        switch (playlistsStyle) {
            case MainUIData.PLAYLISTS_STYLE_GRID:
                mRowMapping.remove(MediaGroup.TYPE_USER_PLAYLISTS);
                mGridMapping.put(MediaGroup.TYPE_USER_PLAYLISTS, getContentService().getPlaylistsObserve());
                updateCategoryType(MediaGroup.TYPE_USER_PLAYLISTS, BrowseSection.TYPE_GRID);
                break;
            case MainUIData.PLAYLISTS_STYLE_ROWS:
                mGridMapping.remove(MediaGroup.TYPE_USER_PLAYLISTS);
                mRowMapping.put(MediaGroup.TYPE_USER_PLAYLISTS, getContentService().getPlaylistRowsObserve());
                updateCategoryType(MediaGroup.TYPE_USER_PLAYLISTS, BrowseSection.TYPE_ROW);
                break;
        }
    }

    /**
     * History as its rows (see ContentService.getHistoryRows), or the grid of its videos with Hide Shorts History.
     * The section is made again when it's shown next.
     */
    public void updateHistoryStyle() {
        updateCategoryType(MediaGroup.TYPE_HISTORY, getHistoryType());
    }

    /**
     * Two rows, like My videos: its videos, then its shorts. With Hide Shorts History, the grid of its videos it was before.
     */
    private static int getHistoryType() {
        return isShortsHistoryHidden() ? BrowseSection.TYPE_GRID : BrowseSection.TYPE_ROW;
    }

    /**
     * Not the Shorts quick toggle's: History isn't one of its sections (see QuickTogglePresenter)
     */
    private static boolean isShortsHistoryHidden() {
        return MediaServiceData.instance().isContentHiddenInSettings(MediaServiceData.CONTENT_SHORTS_HISTORY_ROW);
    }

    private void updateCategoryType(int categoryId, int categoryType) {
        if (categoryType == -1 || categoryId == -1 || mSections == null) {
            return;
        }

        BrowseSection section = mSectionsMapping.get(categoryId);

        if (section != null && section.getType() != categoryType) {
            section.setType(categoryType);
            invalidateCachedSectionIfLayoutChanged(section);
        }

        for (BrowseSection category : mSections) {
            if (category.getId() == categoryId && category.getType() != categoryType) {
                category.setType(categoryType);
                invalidateCachedSectionIfLayoutChanged(category);
                break;
            }
        }
    }

    /**
     * The cache of the previous type is read with the new one and dropped, so it can't be replayed into another fragment. A cache
     * already made for the new type stays (e.g. a grid cache at the next start, when the sections are made as rows first).
     */
    private void invalidateCachedSectionIfLayoutChanged(BrowseSection section) {
        if (mBrowseCache == null || section == null || !isCacheableSection(section)) {
            return;
        }

        if (mBrowseCache.groups(section, getBrowseCacheIdentity()) != null) {
            return;
        }

        // Dropped while its refresh is still loading: the completion must not write the old layout's groups under the new type
        if (mCachedRefreshStarted && mCurrentSection != null && section.getId() == mCurrentSection.getId()) {
            mInvalidatedCachedSections.add(section.getId());
            discardCachedState();
        }
    }

    @Override
    public void onViewDestroyed() {
        super.onViewDestroyed();
        disposeActions();
        saveSelectedItems();
    }

    @Override
    public void onVideoItemSelected(Video item) {
        if (getView() == null) {
            return;
        }

        if (belongsToChannelUploadsMultiGrid(item)) {
            // A fresh cache replay shows both columns: the view auto-selects a channel as its channels arrive, but its uploads
            // are already there, so that one selection loads nothing. This holds when auto load is off too: the cached uploads
            // column must not be cleared by the auto-selection. Every later selection is the user's and loads its channel.
            if (mSkipCachedUploadsSelection) {
                mSkipCachedUploadsSelection = false;

                if (mCachedContentShown && !mCachedRefreshStarted) {
                    mCurrentVideo = item;
                    return;
                }
            }

            if (getMainUIData().isUploadsAutoLoadEnabled()) {
                updateChannelUploadsMultiGrid(item);
            } else {
                updateChannelUploadsMultiGrid(null); // clear
            }
        }

        mCurrentVideo = item;
    }

    @Override
    public void onVideoItemClicked(Video item) {
        if (getContext() == null) {
            return;
        }

        // A Processed tile is about what was processed: it opens with its HQ captions selected, and the player's cut controller
        // offers a ready cut as it does at any video start (#64)
        if (UtubotProcessedOpen.isProcessed(item)) {
            UtubotProcessedOpen.open(getContext(), item);
            return;
        }

        // An Inbox tile is a ready result already: open it where it stands (see UtubotInboxOpen)
        if (UtubotInboxOpen.isInbox(item)) {
            UtubotInboxOpen.open(getContext(), item);
            return;
        }

        // Check that channels new look enabled and we're on the first column
        if (belongsToChannelUploadsMultiGrid(item)) {
            if (getMainUIData().isUploadsAutoLoadEnabled()) {
                VideoActionPresenter.instance(getContext()).apply(item);
            } else {
                updateChannelUploadsMultiGrid(item);
            }
        } else {
            VideoActionPresenter.instance(getContext()).apply(item);
        }
    }

    @Override
    public void removeItem(Video item) {
        removeVideoFromCachedSection(item);
        super.removeItem(item);
    }

    @Override
    protected void removeItemAuthor(Video item) {
        // An author's cards go at once: the cache of the section is dropped instead of patching every row
        invalidateCachedSection();
        super.removeItemAuthor(item);
    }

    /**
     * A card hidden, removed or taken from a playlist at once is taken out of the cache of the section too: the next focus must
     * not replay it (see the Hide, Not interested and playlist-remove callbacks below)
     */
    private void removeVideoFromCachedSection(Video item) {
        if (mBrowseCache == null || mCurrentSection == null || item == null || !isCacheableSection(mCurrentSection)) {
            return;
        }

        // A refresh that is still loading has the card in its own groups too: its completion save is told to leave it out
        if (mCachedRefreshStarted) {
            rememberRemovedCard(mCurrentSection, item);
        }

        List<VideoGroup> groups = mCachedContentShown && mCachedShownGroups != null ?
                mCachedShownGroups : mBrowseCache.groups(mCurrentSection, getBrowseCacheIdentity());

        if (groups == null) {
            return;
        }

        boolean changed = false;

        for (VideoGroup group : groups) {
            int size = group.getSize();

            if (size <= 0) {
                continue;
            }

            Video card = findCard(group, item);

            if (card != null) {
                group.remove(card);
            }

            if (group.getSize() != size) {
                changed = true;
            }
        }

        if (changed) {
            mBrowseCache.save(mCurrentSection, groups, getBrowseCacheIdentity(), System.currentTimeMillis());
        }
    }

    private void invalidateCachedSection() {
        invalidateCachedSection(mCurrentSection);
    }

    private void invalidateCachedSection(BrowseSection section) {
        if (mBrowseCache == null || section == null || !isCacheableSection(section)) {
            return;
        }

        // Dropped while its refresh is still loading: the completion must not write the section's groups back
        if (mCachedRefreshStarted && mCurrentSection != null && section.getId() == mCurrentSection.getId()) {
            mInvalidatedCachedSections.add(section.getId());
        }

        mBrowseCache.save(section, new ArrayList<>(), getBrowseCacheIdentity(), System.currentTimeMillis());

        if (mCurrentSection != null && mCurrentSection.getId() == section.getId()) {
            discardCachedState();
        }
    }

    private void rememberRemovedCard(BrowseSection section, Video item) {
        String key = cardKey(item);

        if (key == null) {
            return;
        }

        Set<String> keys = mRemovedCardsBySection.get(section.getId());

        if (keys == null) {
            keys = new HashSet<>();
            mRemovedCardsBySection.put(section.getId(), keys);
        }

        keys.add(key);
    }

    private static String cardKey(Video video) {
        if (video == null) {
            return null;
        }

        if (!TextUtils.isEmpty(video.videoId)) {
            return "v:" + video.videoId;
        }

        if (!TextUtils.isEmpty(video.channelId)) {
            return "c:" + video.channelId;
        }

        if (!TextUtils.isEmpty(video.channelGroupId)) {
            return "g:" + video.channelGroupId;
        }

        if (!TextUtils.isEmpty(video.playlistId)) {
            return "p:" + video.playlistId;
        }

        return null;
    }

    @Nullable
    private static Video findCard(VideoGroup group, Video item) {
        String key = cardKey(item);

        if (key == null) {
            return null;
        }

        for (Video video : group.getVideos()) {
            if (key.equals(cardKey(video))) {
                return video;
            }
        }

        return null;
    }

    /**
     * A cached refresh's groups without the cards removed while it loaded. The groups are changed in place; the empty ones
     * stay (a multi-grid's column is replaced by an empty one).
     */
    private void removeCardsDuringRefresh(BrowseSection section, List<VideoGroup> groups) {
        Set<String> removed = mRemovedCardsBySection.get(section.getId());

        if (removed == null || groups == null) {
            return;
        }

        for (VideoGroup group : groups) {
            for (Video video : new ArrayList<>(group.getVideos())) {
                if (removed.contains(cardKey(video))) {
                    group.remove(video);
                }
            }
        }
    }

    private boolean isCacheWriteBlocked(BrowseSection section) {
        return section == null || mInvalidatedCachedSections.contains(section.getId());
    }

    private void clearCachedLoadMarks(int sectionId) {
        mRemovedCardsBySection.remove(sectionId);
        mInvalidatedCachedSections.remove(sectionId);
    }

    @Override
    public void onVideoItemLongClicked(Video item) {
        if (getContext() == null) {
            return;
        }

        if (belongsToChannelUploads(item)) { // We need to be sure we exactly on Channels section
            ChannelUploadsMenuPresenter.instance(getContext()).showMenu(item, (videoItem, action) -> {
                if (action == VideoMenuCallback.ACTION_UNSUBSCRIBE) { // works with any uploads section look
                    removeItem(item);
                }
            });
        } else {
            VideoMenuPresenter.instance(getContext()).showMenu(item, (videoItem, action) -> {
                if (action == VideoMenuCallback.ACTION_REMOVE || action == VideoMenuCallback.ACTION_HIDE ||
                    action == VideoMenuCallback.ACTION_REMOVE_FROM_PLAYLIST ||
                    (action == VideoMenuCallback.ACTION_REMOVE_FROM_QUEUE && isPlaybackQueueSection())) {
                    removeItem(videoItem);
                } else if (action == VideoMenuCallback.ACTION_UNSUBSCRIBE && isMultiGridChannelUploadsSection()) {
                    removeItem(mCurrentVideo);
                    VideoMenuPresenter.instance(getContext()).closeDialog();
                } else if (action == VideoMenuCallback.ACTION_UNSUBSCRIBE && isSubscriptionsSection()) {
                    removeItemAuthor(videoItem);
                    VideoMenuPresenter.instance(getContext()).closeDialog();
                } else if (action == VideoMenuCallback.ACTION_REMOVE_AUTHOR) {
                    removeItemAuthor(videoItem);
                }
            });
        }
    }

    /**
     * Shows an edit of Watch later made in the app on the card at once, in the sections the Watch later setting applies to
     * (the sidebar sections, search results and channel pages, see VideoGroup.isHiddenWatchLater):
     * marks it or takes the mark off, or removes it where they're hidden
     */
    private void onWatchLaterEdited(Video video, boolean isAdded) {
        VideoGroup group = video.getGroup();
        int sectionId = group != null ? group.getFilterSectionId() : -1;
        WatchLaterManager manager = WatchLaterManager.instance(getContext());

        if (sectionId == -1 || !manager.isEnabled(sectionId) || WatchLaterManager.isWatchLaterPlaylist(group, video)) {
            return;
        }

        boolean isHidden = manager.isHidden(sectionId);

        if (isHidden && !isAdded) {
            return;
        }

        if (!isHidden) {
            video.isInWatchLater = isAdded;
        }

        for (BasePresenter<?> presenter : getCardPresenters(sectionId)) {
            if (isHidden) {
                presenter.removeItem(video);
            } else {
                presenter.syncItem(video);
            }
        }
    }

    /**
     * The presenters whose screen may show a card of the section
     */
    private List<BasePresenter<?>> getCardPresenters(int sectionId) {
        Context context = getContext();

        if (sectionId != MediaGroup.TYPE_SEARCH && sectionId != MediaGroup.TYPE_CHANNEL) {
            return Collections.singletonList(this);
        }

        if (context == null) {
            return Collections.emptyList();
        }

        // Not the activity: it would become theirs (see setContext)
        context = context.getApplicationContext();

        if (sectionId == MediaGroup.TYPE_SEARCH) {
            return Collections.singletonList(SearchPresenter.instance(context));
        }

        List<BasePresenter<?>> presenters = new ArrayList<>();
        presenters.add(ChannelPresenter.instance(context));
        presenters.add(ChannelUploadsPresenter.instance(context));
        return presenters;
    }

    @Override
    public void onScrollEnd(Video item) {
        if (item == null) {
            Log.e(TAG, "Can't scroll. Video is null.");
            return;
        }

        VideoGroup group = item.getGroup();

        continueGroup(group);
    }

    @Override
    public void onScrollNearEnd(Video item) {
        if (item == null) {
            Log.e(TAG, "Can't scroll. Video is null.");
            return;
        }

        continueGroup(item.getGroup(), false);
    }

    @Override
    public void onSectionFocused(int sectionId) {
        saveSelectedItems(); // save previous state
        mCurrentSection = findSectionById(sectionId);
        mCurrentVideo = null; // fast scroll through the sections (fix empty selected item)

        // Opening the Inbox marks the caller's results read: the state is on the server, shared across the user's clients,
        // so the new-results badge clears here and on the phone and the extension (see updateInboxBadge)
        if (mCurrentSection != null && mCurrentSection.getId() == UtubotInboxSection.ID) {
            mActions.add(RxHelper.execute(UtubotManager.instance(getContext()).readAllInbox()));
        } else {
            // The Inbox is not open: refresh its unread badge, so a result that became ready while watching shows on the rail
            refreshInboxBadge();
        }

        updateCurrentSection();
        restoreSelectedItems(); // Don't place anywhere else
    }

    @Override
    public void onSectionLongPressed(int sectionId) {
        SectionMenuPresenter.instance(getContext()).showMenu(findSectionById(sectionId));
    }

    @Override
    public boolean hasPendingActions() {
        return RxHelper.isAnyActionRunning(mActions);
    }

    public boolean isItemPinned(Video item) {
        Collection<Video> items = getSidebarService().getPinnedItems();

        return items.contains(item);
    }

    public void moveSectionUp(BrowseSection section) {
        mCurrentSection = section; // move current focus
        getSidebarService().moveSectionUp(section.getId());
        updateSections();
    }

    public void moveSectionDown(BrowseSection section) {
        mCurrentSection = section; // move current focus
        getSidebarService().moveSectionDown(section.getId());
        updateSections();
    }

    public void sortSectionsByDefault() {
        getSidebarService().sortSectionsByDefault();
        updateSections();
    }

    /**
     * @param items pinned items of the sidebar (see SidebarService.getPinnedItems), the others come after them
     */
    public void setSectionsOrder(List<Video> items) {
        getSidebarService().setPinnedItemsOrder(items);
        // Once the moves stop: told at each one, with the key held down too (see ReorderListPreferenceDialogFragment)
        Utils.postDelayed(mUpdateSections, 500);
    }

    public void renameSection(BrowseSection section) {
        mCurrentSection = section; // move current focus
        getSidebarService().renameSection(section.getId(), section.getTitle());
        updateSections();
    }

    public void renameSection(Video section) {
        getSidebarService().renameSection(section.getId(), section.getTitle());
        updateSections();
    }

    public void enableAllSections(boolean enable) {
        enableSection(MediaGroup.TYPE_HISTORY, enable);
        enableSection(MediaGroup.TYPE_WATCH_LATER, enable);
        enableSection(MediaGroup.TYPE_USER_PLAYLISTS, enable);
        enableSection(MediaGroup.TYPE_SUBSCRIPTIONS, enable);
        enableSection(MediaGroup.TYPE_CHANNEL_UPLOADS, enable);
        enableSection(MediaGroup.TYPE_GAMING, enable);
        enableSection(MediaGroup.TYPE_MUSIC, enable);
        enableSection(MediaGroup.TYPE_NEWS, enable);
        enableSection(MediaGroup.TYPE_HOME, enable);
        enableSection(MediaGroup.TYPE_SHORTS, enable);
        enableSection(MediaGroup.TYPE_KIDS_HOME, enable);
        enableSection(MediaGroup.TYPE_SPORTS, enable);
        enableSection(MediaGroup.TYPE_LIVE, enable);
        enableSection(MediaGroup.TYPE_MY_VIDEOS, enable);
        enableSection(MediaGroup.TYPE_NOTIFICATIONS, enable);

        if (UtubotSettings.isBuiltIn()) {
            enableSection(UtubotProcessedSection.ID, enable);
        }

        // Hidden by default (see SidebarService.initPinnedItems): only ever hidden here
        if (!enable) {
            enableSection(MediaGroup.TYPE_BLOCKED_CHANNELS, false);
            enableSection(MediaGroup.TYPE_BLOCKED_AI_CHANNELS, false);
        }
    }

    public void enableSection(int sectionId, boolean enable) {
        getSidebarService().enableSection(sectionId, enable);

        if (!enable && mCurrentSection != null && mCurrentSection.getId() == sectionId) {
            mCurrentSection = findNearestSection(sectionId);
        }

        updateSections();
    }

    public void pinItem(Video item) {
        if (getView() == null) {
            return;
        }

        int idx = getSidebarService().addPinnedItem(item);

        createPinnedMapping(item);

        BrowseSection newSection = createPinnedSection(item);
        if (!mSections.contains(newSection)) {
            // Past the end when stored items aren't shown (e.g. a section that isn't there anymore)
            if (idx != -1 && idx <= mSections.size()) {
                mSections.add(idx, newSection);
            } else {
                mSections.add(newSection);
            }
        }
        // The error sections are shown first (see refreshSections)
        getView().addSection(idx != -1 ? idx + mErrorSections.size() : -1, newSection);
    }

    public void pinItem(String title, int resId, ErrorFragmentData data) {
        if (getView() == null) {
            return;
        }

        BrowseSection newSection = new BrowseSection(title.hashCode(), title, BrowseSection.TYPE_ERROR, resId, false, data);
        Helpers.removeIf(mErrorSections, section -> section.getId() == newSection.getId());
        mErrorSections.add(newSection);
        getView().addSection(0, newSection);
    }

    private void appendToSections(String title, int resId, ErrorFragmentData data) {
        int id = title.hashCode();
        Helpers.removeIf(mSections, section -> section.getId() == id);
        mSections.add(new BrowseSection(id, title, BrowseSection.TYPE_ERROR, resId, false, data));
    }

    public void unpinItem(Video item) {
        getSidebarService().removePinnedItem(item);
        getGeneralData().removeSelectedItem(item.getId());

        BrowseSection section = null;

        for (BrowseSection cat : mSections) {
            if (cat.getId() == item.getId()) {
                section = cat;
                break;
            }
        }

        mGridMapping.remove(item.getId());

        if (getView() != null) {
            getView().removeSection(section);
        }
    }

    public void refresh() {
        refresh(true);
    }

    /**
     * The channel of a card of the row of a channel added to Home, which the card doesn't name (see HomeRowsData)
     */
    @Nullable
    public String findAddedHomeRowChannelId(Video video) {
        VideoGroup group = video != null ? video.getGroup() : null;

        if (group == null) {
            return null;
        }

        String channelId = mAddedHomeRowChannelIds.get(group);

        // The rows of the cache aren't made by a load: they carry it
        return channelId != null ? channelId : group.getAddedHomeRowChannelId();
    }

    /**
     * Home is loaded again, with its rows in their new order (see HomeRowsData). From another section, it gets them when it's next shown.
     */
    public void updateHomeRows() {
        if (isHomeSection()) {
            refresh(false);
        }
    }

    public void refresh(boolean focusOnContent) {
        updateCurrentSection(true);
        if (focusOnContent && getView() != null) {
            getView().focusOnContent();
        }
    }

    /**
     * A manual refresh of the section shown now (the refresh button of the modern skin, or its re-selection): from
     * the cache while it keeps the cards and the focused item (like the automatic one), a full reload when there's
     * nothing to show from it. The view's "Refreshing" indicator is on while the load runs.
     */
    public void refreshCurrentSection() {
        if (getView() == null || mCurrentSection == null) {
            return;
        }

        getView().showRefreshing(true);

        if (isCacheableSection(mCurrentSection) && mBrowseCache != null
                && mBrowseCache.groups(mCurrentSection, getBrowseCacheIdentity()) != null) {
            refreshFromCache(mCurrentSection);
        } else {
            refresh(true);
        }
    }

    private void updateRefreshTime() {
        mLastUpdateTimeMs = System.currentTimeMillis();
    }

    private void updateCurrentSection() {
        updateCurrentSection(false);
    }

    private void updateCurrentSection(boolean forceRefresh) {
        disposeActions();

        if (getView() == null || mCurrentSection == null) {
            return;
        }

        Log.d(TAG, "Update section %s", mCurrentSection.getTitle());

        if (mBrowseCache != null && !forceRefresh && showCachedSection(mCurrentSection)) {
            if (browseCacheState(mCurrentSection) == UtubotBrowseCache.State.STALE) {
                startCachedRefresh(mCurrentSection);
            }
            return;
        }

        discardCachedState();
        updateSection(mCurrentSection);
    }

    private boolean showCachedSection(BrowseSection section) {
        if (!isCacheableSection(section)) {
            return false;
        }

        List<VideoGroup> groups = mBrowseCache.groups(section, getBrowseCacheIdentity());

        if (groups == null || getView() == null) {
            return false;
        }

        Log.d(TAG, "Show cached section %s", section.getTitle());
        getView().showProgressBar(false);
        mCachedContentShown = true;
        mCachedShownGroups = groups;
        mCachedReplaySection = section;
        mCachedReplayGroups = groups;
        mCachedRefreshStarted = false;
        mSkipCachedUploadsSelection = section.getType() == BrowseSection.TYPE_MULTI_GRID && section.getId() == MediaGroup.TYPE_CHANNEL_UPLOADS;

        for (VideoGroup group : groups) {
            group.setAction(VideoGroup.ACTION_REPLACE);
            getView().updateSection(group);
        }

        // A header transition may be computing its layout, and the rows' update is then dropped. Retry after it.
        if (getView().isEmpty()) {
            Utils.postDelayed(mReplayCachedGroups, 500);
        }

        return true;
    }

    private void replayCachedGroups() {
        if (!mCachedContentShown || getView() == null || mCurrentSection != mCachedReplaySection || mCachedReplayGroups == null) {
            return;
        }

        for (VideoGroup group : mCachedReplayGroups) {
            group.setAction(VideoGroup.ACTION_REPLACE);
            getView().updateSection(group);
        }
    }

    private void startCachedRefresh(BrowseSection section) {
        mCachedRefreshStarted = true;
        mBrowseCache.markAttempt(section.getId(), System.currentTimeMillis());
        updateSection(section);
    }

    private void refreshFromCache(BrowseSection section) {
        if (!isCacheableSection(section)) {
            return;
        }

        List<VideoGroup> groups = mBrowseCache.groups(section, getBrowseCacheIdentity());

        if (groups == null) {
            return;
        }

        mCachedContentShown = true;
        mCachedShownGroups = groups;
        mCachedRefreshStarted = true;
        mBrowseCache.markAttempt(section.getId(), System.currentTimeMillis());
        Log.d(TAG, "Refresh cached section %s", section.getTitle());
        updateSection(section);
    }

    private boolean isCacheableSection(BrowseSection section) {
        if (section == null || section.getId() == MediaGroup.TYPE_HIDDEN_VIDEOS || mLocalGridMappings.containsKey(section.getId())) {
            return false;
        }

        switch (section.getType()) {
            case BrowseSection.TYPE_GRID:
            case BrowseSection.TYPE_SHORTS_GRID:
            case BrowseSection.TYPE_ROW:
            case BrowseSection.TYPE_MULTI_GRID:
                return true;
            default:
                return false;
        }
    }

    private UtubotBrowseCache.State browseCacheState(BrowseSection section) {
        return mBrowseCache.state(section.getId(), section.getType(), getBrowseCacheIdentity(), System.currentTimeMillis(),
                browseRefreshMinutes());
    }

    private int browseRefreshMinutes() {
        return UtubotSettings.instance(getContext()).getBrowseRefreshMinutes();
    }

    private String getBrowseCacheIdentity() {
        Account account = MediaServiceManager.instance().getSelectedAccount();
        String profile = account != null && !account.isEmpty() ? account.getProfileName() : "";

        return LocaleUtility.getCurrentLocale(getContext()).toString() + "|" + profile;
    }

    private void saveCachedGroups(BrowseSection section, List<VideoGroup> groups) {
        if (mBrowseCache == null || !isCacheableSection(section) || isCacheWriteBlocked(section)) {
            return;
        }

        removeCardsDuringRefresh(section, groups);
        mBrowseCache.save(section, groups, getBrowseCacheIdentity(), System.currentTimeMillis());
    }

    private void saveCachedGroup(BrowseSection section, VideoGroup group) {
        if (mBrowseCache == null || !isCacheableSection(section) || group == null) {
            return;
        }

        removeCardsDuringRefresh(section, Collections.singletonList(group));

        if (section.getType() == BrowseSection.TYPE_MULTI_GRID) {
            saveCachedGroups(section, UtubotBrowseCache.mergeByPosition(mBrowseCache.groups(section, getBrowseCacheIdentity()), group));
            return;
        }

        saveCachedGroups(section, Collections.singletonList(group));
    }

    private void appendCachedGroup(BrowseSection section, VideoGroup group) {
        if (mBrowseCache == null || !isCacheableSection(section) || isCacheWriteBlocked(section)) {
            return;
        }

        removeCardsDuringRefresh(section, Collections.singletonList(group));
        mBrowseCache.append(section, group, getBrowseCacheIdentity(), System.currentTimeMillis());
    }

    /**
     * @param column the multi-grid column of the failed load (0 channels, 1 uploads), or -1 when the load isn't a column's
     */
    private boolean handleCachedRefreshError(Throwable error, BrowseSection section, int column) {
        mCachedRefreshStarted = false;
        // No channels are coming to be auto-selected: the next selection is the user's
        mSkipCachedUploadsSelection = false;

        if (!mCachedContentShown || getView() == null) {
            return false;
        }

        getView().showProgressBar(false);
        getView().showRefreshing(false);

        // The cached cards are still on screen: the flag stays set, so they're protected as cached until the section is left
        // or loaded again. A multi-grid clears its other column as its refreshed column arrives, so the cached uploads are shown
        // again when their load fails.
        if (section.getType() == BrowseSection.TYPE_MULTI_GRID && column == 1) {
            restoreCachedColumn(1);
        }

        Log.d(TAG, "Keep the cached section %s: %s", mCurrentSection != null ? mCurrentSection.getTitle() : null, error);

        return true;
    }

    /**
     * A cached column of a multi-grid on screen again, e.g. its uploads after their refresh failed (the channels' arrival cleared
     * the view's uploads column)
     */
    private void restoreCachedColumn(int column) {
        if (mCachedShownGroups == null || getView() == null) {
            return;
        }

        for (VideoGroup oldGroup : mCachedShownGroups) {
            if (oldGroup.getPosition() == column) {
                oldGroup.setAction(VideoGroup.ACTION_REPLACE);
                getView().updateSection(oldGroup);
                return;
            }
        }
    }

    /**
     * The load of the section is whole: the cards on screen are its content of now, not cached ones. A multi-grid writes a column
     * at a time, so the other column's cached cards stay protected until that column is loaded too.
     *
     * @param column the multi-grid column of this load (0 channels, 1 uploads), or -1 when the load isn't a column's
     */
    private void finishCachedRefresh(BrowseSection section, int column) {
        if (section.getType() == BrowseSection.TYPE_MULTI_GRID && column != 1) {
            return;
        }

        clearCachedLoadMarks(section.getId());
        discardCachedState();
        if (getView() != null) {
            getView().showRefreshing(false);
        }
    }

    private void discardCachedState() {
        mCachedContentShown = false;
        mCachedShownGroups = null;
        mCachedReplaySection = null;
        mCachedReplayGroups = null;
        mCachedRefreshStarted = false;
        mSkipCachedUploadsSelection = false;
        Utils.removeCallbacks(mReplayCachedGroups);
    }

    private void restoreCachedFocusedItem(VideoGroup group, Video focusedBefore) {
        if (focusedBefore == null || getView() == null || group == null) {
            return;
        }

        for (Video video : group.getVideos()) {
            if (Helpers.equals(video.videoId, focusedBefore.videoId) && Helpers.equals(video.playlistId, focusedBefore.playlistId)) {
                getView().selectSectionItem(video);
                mCurrentVideo = video;
                break;
            }
        }
    }

    private void updateSection(BrowseSection section) {
        mIsChannelContent = false;

        switch (section.getType()) {
            case BrowseSection.TYPE_GRID:
            case BrowseSection.TYPE_SHORTS_GRID:
                if (mGridMapping.containsKey(section.getId())) {
                    Observable<MediaGroup> group = mGridMapping.get(section.getId());
                    updateVideoGrid(section, group, section.isAuthOnly());
                 } else if (mProcessedMapping.containsKey(section.getId())) {
                     updateProcessedGrid(section);
                 } else if (mInboxMapping.containsKey(section.getId())) {
                     updateInboxGrid(section);
                 } else if (mLocalGridMappings.containsKey(section.getId())) {
                    Callable<List<Video>> localVideos = mLocalGridMappings.get(section.getId());
                    updateLocalGrid(section, localVideos);
                }
                break;
            case BrowseSection.TYPE_ROW:
                if (section.getId() == MediaGroup.TYPE_HIDDEN_VIDEOS) {
                    updateHiddenVideoRows(section);
                    break;
                }

                Observable<List<MediaGroup>> groups = mRowMapping.get(section.getId());
                updateVideoRows(section, groups, section.isAuthOnly());
                break;
            case BrowseSection.TYPE_SETTINGS_GRID:
                Callable<List<SettingsItem>> items = mSettingsGridMapping.get(section.getId());
                updateSettingsGrid(section, items);
                break;
            case BrowseSection.TYPE_MULTI_GRID:
                Observable<MediaGroup> group2 = mGridMapping.get(section.getId());
                updateVideoGrid(section, group2, 0, section.isAuthOnly());
                break;
            case BrowseSection.TYPE_ERROR:
                getView().showProgressBar(false);
                break;
        }

        updateRefreshTime();
    }

    private void updateSettingsGrid(BrowseSection section, Callable<List<SettingsItem>> items) {
        getView().updateSection(SettingsGroup.from(Helpers.get(items), section));
        getView().showProgressBar(false);
    }

    private void updateLocalGrid(BrowseSection section, Callable<List<Video>> items) {
        VideoGroup videoGroup = VideoGroup.from(Helpers.get(items), section);
        videoGroup.setAction(VideoGroup.ACTION_REPLACE);
        videoGroup.setId(videoGroup.hashCode());
        videoGroup.setTitle(section.getTitle());
        getView().updateSection(videoGroup);
        getView().showProgressBar(false);
        saveCachedGroups(section, Collections.singletonList(videoGroup));
    }

    /**
     * A row per section the videos were hidden from (see HiddenVideosData.sortForRows), the newest hidden first. Kept on the device:
     * signed out too, and nothing to load or continue.
     */
    private void updateHiddenVideoRows(BrowseSection section) {
        VideoGroup clear = VideoGroup.from(section);
        clear.setAction(VideoGroup.ACTION_REPLACE);
        getView().updateSection(clear);

        List<HiddenVideosData.Section> hiddenSections = HiddenVideosData.sortForRows(HiddenVideosData.instance(getContext()).getSections(),
                getSidebarService().getDefaultSections().values());

        for (HiddenVideosData.Section hidden : hiddenSections) {
            // A list of its own: the row's cards are removed from it (see VideoGroup.remove)
            VideoGroup row = VideoGroup.from(new ArrayList<>(hidden.videos), section, -1);
            row.setId(row.hashCode());
            row.setTitle(getHiddenVideosRowTitle(hidden));
            row.setHiddenFromSection(hidden.sectionId);
            getView().updateSection(row);
        }

        getView().showProgressBar(false);
    }

    /**
     * The section's title of now: a pinned one (e.g. a channel) can be renamed, otherwise the one it had when a video was hidden there
     */
    private String getHiddenVideosRowTitle(HiddenVideosData.Section hidden) {
        switch (hidden.sectionId) {
            case SectionFilterData.SECTION_CHANNEL_GROUPS:
                return getContext().getString(R.string.subscription_groups);
            case MediaGroup.TYPE_SEARCH:
                return getContext().getString(R.string.action_search);
            case MediaGroup.TYPE_CHANNEL:
                return getContext().getString(R.string.unhide_channel_pages);
            case MediaGroup.TYPE_SUGGESTIONS:
                return getContext().getString(R.string.suggestions);
        }

        for (Entry<Integer, Integer> defaultSection : getSidebarService().getDefaultSections().entrySet()) {
            if (defaultSection.getValue() == hidden.sectionId) {
                return getContext().getString(defaultSection.getKey());
            }
        }

        BrowseSection pinned = findSectionById(hidden.sectionId);

        return pinned != null ? pinned.getTitle() : hidden.title;
    }

    private void updateVideoRows(BrowseSection section, Observable<List<MediaGroup>> groups, boolean authCheck) {
        Log.d(TAG, "loadRowsHeader: Start loading section: " + section.getTitle());

        authCheck(authCheck, () -> updateVideoRows(section, groups));
    }

    private void updateVideoGrid(BrowseSection section, Observable<MediaGroup> group, boolean authCheck) {
        updateVideoGrid(section, group, -1, authCheck);
    }

    private void updateVideoGrid(BrowseSection section, Observable<MediaGroup> group, int column, boolean authCheck) {
        Log.d(TAG, "loadMultiGridHeader: Start loading section: " + section.getTitle());

        authCheck(authCheck, () -> updateVideoGrid(section, group, column));
    }

    private void updateVideoRows(BrowseSection section, Observable<List<MediaGroup>> groups) {
        Log.d(TAG, "updateRowsHeader: Start loading section: " + section.getTitle());

        disposeActions();
        // A cache dropped by the last, aborted refresh is rebuilt by this one
        mInvalidatedCachedSections.remove(section.getId());

        if (getView() == null) {
            Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
            getViewManager().startView(BrowseView.class);
            return;
        }
        
        boolean cached = mCachedContentShown && mCachedShownGroups != null;

        getView().showProgressBar(!cached);

        if (!cached) {
            VideoGroup firstGroup = VideoGroup.from(section);
            firstGroup.setAction(VideoGroup.ACTION_REPLACE);
            getView().updateSection(firstGroup);
        }

        if (groups == null) {
            // No group. Maybe just clear.
            getView().showProgressBar(false);
            return;
        }

        // Not where Home is loaded: a load of its content elsewhere (e.g. the preview of KeywordFilterSettingsPresenter) runs alongside
        if (section.getId() == MediaGroup.TYPE_HOME) {
            mAddedHomeRows.clear();
            mAddedHomeRowChannelIds.clear();
        }

        AtomicInteger groupIndex = new AtomicInteger(-1);
        // The rows of this load share it: a video is kept by the first row that has it
        DuplicateFilter duplicateFilter = DuplicatesData.instance(getContext()).isSectionEnabled(section.getId()) ? new DuplicateFilter() : null;
        // Sections emit their rows in parts (e.g. Music: its "Liked music" row, then its rows; Playlists: one per playlist).
        // The cache of the whole section is written once, from all the parts of this load. Its stale rows are taken out then too:
        // a part that hasn't arrived yet mustn't have its cached rows cleared.
        List<VideoGroup> loadedGroups = new ArrayList<>();
        Set<Integer> usedCachedIds = new HashSet<>();

        Disposable updateAction = HiddenVideoResolver.resolveGroups(getContext(), VideoCategoryManager.instance(getContext()).resolveGroups(groups), section)
                // The rows that lost their videos to Hide content get the next ones before they're shown
                .concatMap(mediaGroups -> MediaServiceManager.instance().fillRowGroups(getContext(),
                        createRowGroups(section, mediaGroups, groupIndex, duplicateFilter), this::continueGroupObserve))
                .subscribe(
                        videoGroups -> {
                            // E.g. the app is closing while the rows are filled
                            if (getView() == null) {
                                Log.e(TAG, "Can't show the rows. The view is null.");
                                return;
                            }

                            getView().showProgressBar(false);

                            for (VideoGroup videoGroup : videoGroups) {
                                appendLocalHistory(videoGroup, isShortsRow(videoGroup), false);

                                if (cached) {
                                    int oldId = UtubotBrowseCache.findOldId(mCachedShownGroups, videoGroup);

                                    if (oldId != -1) {
                                        videoGroup.setId(oldId);
                                        videoGroup.setAction(VideoGroup.ACTION_REPLACE);
                                        usedCachedIds.add(oldId);
                                    }
                                }

                                Video focusedBefore = mCurrentVideo;
                                getView().updateSection(videoGroup);

                                if (cached && videoGroup.getAction() == VideoGroup.ACTION_REPLACE) {
                                    restoreCachedFocusedItem(videoGroup, focusedBefore);
                                }

                                mBrowseProcessor.process(videoGroup);
                                MediaServiceManager.instance().warmUpPlaybackIfNeeded(videoGroup);

                                continueGroupIfNeeded(videoGroup, false);

                                loadedGroups.add(videoGroup);
                            }

                            // With the rows of the account, not popping in after them: History emits its rows together
                            addMissingLocalHistoryRows(videoGroups);
                        },
                        error -> {
                            Log.e(TAG, "updateRowsHeader error: %s", error.getMessage());
                            if (handleCachedRefreshError(error, section, -1)) {
                                return;
                            }
                            handleLoadError(error);
                        }, () -> {
                            if (cached) {
                                removeStaleCachedRows(section, usedCachedIds);
                            }

                            // Once, with every part: the first parts keep their rows in the cache, and a failure of a later one
                            // leaves the cache of the last whole load.
                            saveCachedGroups(section, loadedGroups);

                            finishCachedRefresh(section, -1);

                            // The account's History has no video: the ones watched here instead, as the History grid had them
                            if (isHistorySection() && getView() != null && getView().isEmpty() && !VideoStateService.instance(getContext()).isEmpty()) {
                                updateLocalHistoryRows();
                                return;
                            }

                            handleLoadError(null);
                        });

        mActions.add(updateAction);
    }

    /**
     * @param duplicateFilter the videos of the rows created before, or null to keep them
     */
    private List<VideoGroup> createRowGroups(BrowseSection section, List<MediaGroup> mediaGroups, AtomicInteger groupIndex,
                                             DuplicateFilter duplicateFilter) {
        List<VideoGroup> result = new ArrayList<>();

        filterHomeIfNeeded(mediaGroups);

        for (MediaGroup mediaGroup : mediaGroups) {
            if (mediaGroup.isEmpty()) {
                Log.e(TAG, "loadRowsHeader: MediaGroup is empty. Group Name: " + mediaGroup.getTitle());
                continue;
            }

            // Before its videos: a subscription group may hide its channels from the Subscriptions row (see ChannelGroupFilter)
            Row addedRow = mAddedHomeRows.get(mediaGroup);
            VideoGroup videoGroup = VideoGroup.from(mediaGroup, section, groupIndex.get() + 1, duplicateFilter, addedRow);

            // The rows of History, and the row of shorts of My videos (its cards are all shorts), under titles of their own rather than
            // the section's or YouTube's
            if (section.getId() == MediaGroup.TYPE_HISTORY) {
                videoGroup.setTitle(getContext().getString(
                        mediaGroup.getRowKind() == MediaGroup.ROW_KIND_SHORTS ? R.string.history_shorts : R.string.history_videos));
            } else if (section.getId() == MediaGroup.TYPE_MY_VIDEOS && videoGroup.isShorts()) {
                videoGroup.setTitle(getContext().getString(R.string.my_shorts));
            }

            // Named after the channel, the subscription group, or Subscriptions
            if (addedRow != null) {
                String title = getAddedHomeRowTitle(addedRow);

                if (title != null) {
                    videoGroup.setTitle(title);
                }

                if (addedRow.type == Row.TYPE_CHANNEL) {
                    mAddedHomeRowChannelIds.put(videoGroup, addedRow.channelId);
                }
            }

            // A card alone says nothing, e.g. "More music" of a row that lost its videos to Hide content.
            // A hidden row of channels or topics isn't continued in search of cards to show (see GroupFiller).
            if (videoGroup.hasOnlyHiddenVideos() || videoGroup.isHiddenRow()) {
                continue;
            }

            groupIndex.incrementAndGet();

            if (TextUtils.isEmpty(videoGroup.getTitle())) {
                videoGroup.setTitle(getContext().getString(R.string.suggestions));
            }

            result.add(videoGroup);
        }

        return result;
    }

    /**
     * A subscription group under its title of now: it can be renamed
     */
    @Nullable
    private String getAddedHomeRowTitle(Row row) {
        if (row.type == Row.TYPE_SUBSCRIPTIONS) {
            return getContext().getString(R.string.header_subscriptions);
        }

        if (row.type == Row.TYPE_CHANNEL_GROUP) {
            ItemGroup group = ChannelGroupServiceWrapper.instance(getContext()).findChannelGroupById(row.channelGroupId);

            if (group != null) {
                return group.getTitle();
            }
        }

        return row.title;
    }

    private void updateVideoGrid(BrowseSection section, Observable<MediaGroup> group, int column) {
        disposeActions();
        // A cache dropped by the last, aborted refresh is rebuilt by this one
        mInvalidatedCachedSections.remove(section.getId());

        if (getView() == null) {
            Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
            getViewManager().startView(BrowseView.class);
            return;
        }

        Log.d(TAG, "updateGridHeader: Start loading section: " + section.getTitle());

        boolean cached = mCachedContentShown && mCachedShownGroups != null;

        getView().showProgressBar(!cached);

        // Stay on the same group in case of multiple subscribe calls
        VideoGroup baseGroup = VideoGroup.from(section, column);
        baseGroup.setAction(VideoGroup.ACTION_REPLACE);

        if (!cached) {
            getView().updateSection(baseGroup);
        }

        if (group == null) {
            // No group. Maybe just clear.
            getView().showProgressBar(false);
            return;
        }

        Disposable updateAction = HiddenVideoResolver.resolveGroup(getContext(), VideoCategoryManager.instance(getContext()).resolveGroup(group), section)
                .subscribe(
                        mediaGroup -> {
                            getView().showProgressBar(false);

                            if (getView() == null) {
                                Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
                                getViewManager().startView(BrowseView.class);
                                return;
                            }

                            VideoGroup videoGroup = VideoGroup.from(baseGroup, mediaGroup);
                            // The grid of History with Hide Shorts History: the videos watched here, its shorts hidden too
                            appendLocalHistory(videoGroup, false, videoGroup.isEmpty());

                            if (cached) {
                                int oldId = findCachedGroupId(videoGroup.getPosition());

                                videoGroup.setAction(VideoGroup.ACTION_REPLACE);

                                if (oldId != -1) {
                                    videoGroup.setId(oldId);
                                }
                            }

                            Video focusedBefore = mCurrentVideo;
                            getView().updateSection(videoGroup);

                            if (cached) {
                                restoreCachedFocusedItem(videoGroup, focusedBefore);
                            }

                            mBrowseProcessor.process(videoGroup);
                            MediaServiceManager.instance().warmUpPlaybackIfNeeded(videoGroup);
                            saveCachedGroup(section, videoGroup);

                            continueGroupIfNeeded(videoGroup);
                        },
                        error -> {
                            Log.e(TAG, "updateGridHeader error: %s", error.getMessage());
                            if (handleCachedRefreshError(error, section, column)) {
                                return;
                            }
                            handleLoadError(error);
                        }, () -> {
                            finishCachedRefresh(section, column);
                            handleLoadError(null);
                        });

        mActions.add(updateAction);
    }

    /**
     * The u-tubot Processed section: its tiles from the backend answer, newest first as it lists them. YouTube's filters and
     * pages don't apply; its cards are cached as the other grid sections' (see UtubotBrowseCache). Empty and failed loads say
     * so in a u-tubot message (see UtubotSectionError), and a cached section keeps its cards on a failed refresh.
     */
    private void updateProcessedGrid(BrowseSection section) {
        disposeActions();
        mInvalidatedCachedSections.remove(section.getId());

        if (getView() == null) {
            Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
            getViewManager().startView(BrowseView.class);
            return;
        }

        // No backend yet: the section says how to set one instead of failing with "Bad backend address"
        if (!UtubotSettings.instance(getContext()).isConfigured()) {
            getView().showProgressBar(false);
            getView().showError(UtubotSectionError.notConfigured(getContext()));
            return;
        }

        Observable<ProcessedList> processed = mProcessedMapping.get(section.getId());

        if (processed == null) {
            return;
        }

        Log.d(TAG, "updateProcessedGrid: Start loading section: " + section.getTitle());

        boolean cached = mCachedContentShown && mCachedShownGroups != null;

        getView().showProgressBar(!cached);

        if (!cached) {
            VideoGroup clear = VideoGroup.from(section);
            clear.setAction(VideoGroup.ACTION_REPLACE);
            getView().updateSection(clear);
        }

        Disposable updateAction = processed.observeOn(AndroidSchedulers.mainThread())
                .subscribe(
                        list -> {
                            if (getView() == null) {
                                Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
                                getViewManager().startView(BrowseView.class);
                                return;
                            }

                            getView().showProgressBar(false);

                            VideoGroup videoGroup = UtubotProcessedSection.toGroup(getContext(), section, list);

                            if (cached) {
                                int oldId = findCachedGroupId(videoGroup.getPosition());

                                if (oldId != -1) {
                                    videoGroup.setId(oldId);
                                }
                            }

                            Video focusedBefore = mCurrentVideo;
                            getView().updateSection(videoGroup);

                            if (cached) {
                                restoreCachedFocusedItem(videoGroup, focusedBefore);
                            }

                            mBrowseProcessor.process(videoGroup);
                            saveCachedGroup(section, videoGroup);

                            if (videoGroup.isEmpty()) {
                                getView().showError(UtubotSectionError.empty(getContext()));
                            }
                        },
                        error -> {
                            Log.e(TAG, "updateProcessedGrid error: %s", error.getMessage());
                            if (handleCachedRefreshError(error, section, -1)) {
                                return;
                            }
                            // E.g. the app is closing while the backend answers
                            if (getView() == null) {
                                return;
                            }
                            getView().showProgressBar(false);
                            getView().showRefreshing(false);
                            getView().showError(UtubotSectionError.failed(getContext(), error));
                        }, () -> {
                            finishCachedRefresh(section, -1);
                        });

        mActions.add(updateAction);
    }

    /**
     * The u-tubot Inbox section: its tiles from the backend answer, newest first as it lists them (see UtubotInboxSection). One tile
     * per ready result, with its unread count in the section title (the badge, u-tubot #160). Empty and failed loads say so in a
     * u-tubot message, and a cached section keeps its cards on a failed refresh.
     */
    private void updateInboxGrid(BrowseSection section) {
        disposeActions();
        mInvalidatedCachedSections.remove(section.getId());

        if (getView() == null) {
            Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
            getViewManager().startView(BrowseView.class);
            return;
        }

        // No backend yet: the section says how to set one instead of failing with "Bad backend address"
        if (!UtubotSettings.instance(getContext()).isConfigured()) {
            getView().showProgressBar(false);
            getView().showError(UtubotSectionError.notConfigured(getContext()));
            return;
        }

        Observable<InboxList> inbox = mInboxMapping.get(section.getId());

        if (inbox == null) {
            return;
        }

        Log.d(TAG, "updateInboxGrid: Start loading section: " + section.getTitle());

        boolean cached = mCachedContentShown && mCachedShownGroups != null;

        getView().showProgressBar(!cached);

        if (!cached) {
            VideoGroup clear = VideoGroup.from(section);
            clear.setAction(VideoGroup.ACTION_REPLACE);
            getView().updateSection(clear);
        }

        Disposable updateAction = inbox.observeOn(AndroidSchedulers.mainThread())
                .subscribe(
                        list -> {
                            if (getView() == null) {
                                Log.e(TAG, "Browse view has been unloaded from the memory. Low RAM?");
                                getViewManager().startView(BrowseView.class);
                                return;
                            }

                            getView().showProgressBar(false);

                            updateInboxBadge(section, list);

                            VideoGroup videoGroup = UtubotInboxSection.toGroup(getContext(), section, list);

                            if (cached) {
                                int oldId = findCachedGroupId(videoGroup.getPosition());

                                if (oldId != -1) {
                                    videoGroup.setId(oldId);
                                }
                            }

                            Video focusedBefore = mCurrentVideo;
                            getView().updateSection(videoGroup);

                            if (cached) {
                                restoreCachedFocusedItem(videoGroup, focusedBefore);
                            }

                            mBrowseProcessor.process(videoGroup);
                            saveCachedGroup(section, videoGroup);

                            if (videoGroup.isEmpty()) {
                                getView().showError(UtubotSectionError.empty(getContext()));
                            }
                        },
                        error -> {
                            Log.e(TAG, "updateInboxGrid error: %s", error.getMessage());
                            if (handleCachedRefreshError(error, section, -1)) {
                                return;
                            }
                            if (getView() == null) {
                                return;
                            }
                            getView().showProgressBar(false);
                            getView().showError(UtubotSectionError.failed(getContext(), error));
                        }, () -> {
                            finishCachedRefresh(section, -1);
                        });

        mActions.add(updateAction);
    }

    /**
     * The Inbox rail's badge: the unread count, so the rail shows new results without opening the section. The count is shared per
     * user (the phone and the extension see the same), so it is the same everywhere. Set while the Inbox is not open, cleared while it
     * is open (the results are on the screen the user is looking at). The old guard returned before setting the badge whenever the
     * Inbox was open, which was the only time this ran, so the badge never showed.
     */
    private void updateInboxBadge(BrowseSection section, InboxList list) {
        if (getView() == null || list == null || list.items == null) {
            return;
        }

        mInboxUnread = list.unreadCount();
        String baseTitle = getContext().getString(R.string.utubot_inbox_title);

        // The Inbox is open: the results are on screen, so the badge clears (and on the phone and the extension)
        if (mCurrentSection != null && mCurrentSection.getId() == UtubotInboxSection.ID) {
            getView().updateSectionTitle(section.getId(), baseTitle);
            return;
        }

        // The Inbox is not open (watching, another section): the unread count is the badge, refreshed when the browse UI returns
        // (see refreshInboxBadge). Empty means none.
        if (mInboxUnread <= 0) {
            getView().updateSectionTitle(section.getId(), baseTitle);
            return;
        }

        section.setTitle(getContext().getString(R.string.utubot_inbox_badge, mInboxUnread));
        getView().updateSectionTitle(section.getId(), section.getTitle());
    }

    /**
     * Re-check the Inbox's unread count so the rail shows a result that became ready after the viewer left the Inbox (a cut ready
     * while watching). Best-effort: a backend that does not answer leaves the badge as it is. Called when the browse UI returns, so
     * the badge is fresh without opening the Inbox (see onViewResumed and onSectionFocused).
     */
    private void refreshInboxBadge() {
        if (System.currentTimeMillis() - mInboxBadgeLastRefreshMs < INBOX_BADGE_REFRESH_MS) {
            return;
        }
        mInboxBadgeLastRefreshMs = System.currentTimeMillis();

        BrowseSection inboxSection = findSectionById(UtubotInboxSection.ID);
        Observable<InboxList> inbox = (inboxSection == null) ? null : mInboxMapping.get(UtubotInboxSection.ID);
        if (getView() == null || inbox == null || inboxSection == null) {
            return;
        }

        // Tracked apart from the section loads: a section load disposes the actions and would drop the badge refresh before it
        // answers. Dispose the previous refresh so the latest one wins, then subscribe again.
        if (mInboxBadgeAction != null) {
            mInboxBadgeAction.dispose();
        }

        Log.d(TAG, "Refresh the Inbox unread badge");
        mInboxBadgeAction = inbox.observeOn(AndroidSchedulers.mainThread())
                .subscribe(item -> updateInboxBadge(inboxSection, item),
                        error -> Log.d(TAG, "Can't refresh the Inbox badge: %s", error.getMessage()));
    }

    private int findCachedGroupId(int position) {
        if (mCachedShownGroups == null) {
            return -1;
        }

        for (VideoGroup oldGroup : mCachedShownGroups) {
            if (oldGroup.getPosition() == position) {
                return oldGroup.getId();
            }
        }

        return -1;
    }

    private void removeStaleCachedRows(BrowseSection section, Set<Integer> usedCachedIds) {
        // The view or the cached rows may be gone when the whole load completes (the app is closing, or another account is
        // selected)
        if (mCachedShownGroups == null || getView() == null) {
            return;
        }

        for (VideoGroup oldGroup : mCachedShownGroups) {
            if (usedCachedIds.contains(oldGroup.getId())) {
                continue;
            }

            VideoGroup stale = VideoGroup.from(section, oldGroup.getPosition());
            stale.setId(oldGroup.getId());
            stale.setAction(VideoGroup.ACTION_REPLACE);
            getView().updateSection(stale);
        }
    }

    private void continueGroup(VideoGroup group) {
        continueGroup(group, true);
    }

    private void continueGroup(VideoGroup group, boolean showLoading) {
        continueGroup(group, showLoading, 0);
    }

    /**
     * @param duplicatePages the pages just before this one that had only videos the rows already have (see DuplicateFilter)
     */
    private void continueGroup(VideoGroup group, boolean showLoading, int duplicatePages) {
        if (getView() == null) {
            Log.e(TAG, "Can't continue group. The view is null.");
            return;
        }

        if (group == null) {
            Log.e(TAG, "Can't continue group. The group is null.");
            return;
        }

        if (getCurrentSection() != null && (mLocalGridMappings.containsKey(getCurrentSection().getId())
                || getCurrentSection().getId() == MediaGroup.TYPE_HIDDEN_VIDEOS)) {
            Log.d(TAG, "Local section doesn't assume a continuation...");
            return;
        }

        Log.d(TAG, "continueGroup: start continue group: " + group.getTitle());

        // Small amount of items == small load time. Loading bar are useless?
        if (showLoading) {
            getView().showProgressBar(true);
        }

        int size = group.getSize();
        int duplicateCount = group.getDuplicateCount();

        Disposable continueAction = continueGroupObserve(group)
                .subscribe(
                        continueGroup -> {
                            if (getView() == null) {
                                Log.e(TAG, "Can't continue group. The view is null.");
                                return;
                            }

                            getView().showProgressBar(false);

                            VideoGroup videoGroup = VideoGroup.from(group, continueGroup);
                            getView().updateSection(videoGroup);
                            mBrowseProcessor.process(videoGroup);
                            BrowseSection section = videoGroup.getSection();
                            appendCachedGroup(section != null ? section : getCurrentSection(), videoGroup);

                            // Nothing new to show: the row would stop at the card that asked for the page
                            if (videoGroup.getSize() == size && videoGroup.getDuplicateCount() > duplicateCount
                                    && videoGroup.getNextPageKey() != null && duplicatePages + 1 < MAX_DUPLICATE_PAGES) {
                                continueGroup(videoGroup, showLoading, duplicatePages + 1);
                                return;
                            }

                            continueGroupIfNeeded(videoGroup, showLoading);
                        },
                        error -> {
                            Log.e(TAG, "continueGroup error: %s", error.getMessage());
                            if (getView() != null) {
                                getView().showProgressBar(false);
                            }
                        },
                        () -> {
                            if (getView() != null) {
                                getView().showProgressBar(false);
                            }
                        }
                );

        mActions.add(continueAction);
    }

    private Observable<MediaGroup> continueGroupObserve(VideoGroup group) {
        MediaGroup mediaGroup = group.getMediaGroup();

        //if (mediaGroup.getType() == MediaGroup.TYPE_SUGGESTIONS) { // Pinned playlist
        //    continuation = mItemService.continueGroupObserve(mediaGroup);
        //} else {
        //    continuation = getContentService().continueGroupObserve(mediaGroup);
        //}

        return HiddenVideoResolver.resolveGroup(getContext(),
                VideoCategoryManager.instance(getContext()).resolveGroup(getContentService().continueGroupObserve(mediaGroup)), group.getSection());
    }

    private void authCheck(boolean check, Runnable callback) {
        if (!check) {
            callback.run();
            return;
        }

        getView().showProgressBar(true);

        if (getSignInService().isSigned()) {
            callback.run();
        } else if (getView() != null) {
            if (isHistorySection() && !VideoStateService.instance(getContext()).isEmpty()) {
                updateLocalHistoryRows();
            } else {
                getView().showProgressBar(false);
                getView().showError(new SignInError(getContext()));
            }
        }
    }

    /**
     * Most tiny ui has 8 cards in a row or 24 in grid.
     */
    private void continueGroupIfNeeded(VideoGroup group) {
        continueGroupIfNeeded(group, true);
    }

    /**
     * Most tiny ui has 8 cards in a row or 24 in grid.
     */
    private void continueGroupIfNeeded(VideoGroup group, boolean showLoading) {
        if (MediaServiceManager.instance().shouldContinueTheGroup(getContext(), group, isGridSection())) {
            continueGroup(group, showLoading);
        }
    }

    private void disposeActions() {
        RxHelper.disposeActions(mActions);
        Utils.removeCallbacks(mRefreshSection);
        mLastUpdateTimeMs = -1;
        mBrowseProcessor.dispose();
    }

    private void updateChannelUploadsMultiGrid(Video item) {
        if (mCurrentSection == null) {
            return;
        }

        mIsChannelContent = Skins.getTraits().keepsSectionOnChannelError();
        updateVideoGrid(mCurrentSection, ChannelUploadsPresenter.instance(getContext()).obtainUploadsObservable(item), 1, false);
    }

    private boolean belongsToChannelUploadsMultiGrid(Video item) {
        return isMultiGridChannelUploadsSection() && belongsToChannelUploads(item);
    }

    private boolean belongsToChannelUploads(Video item) {
        return item.belongsToChannelUploads() && !item.hasVideo();
    }

    @Nullable
    public BrowseSection getCurrentSection() {
        return mCurrentSection;
    }

    /**
     * The sidebar sections with videos from YouTube (e.g. not Channels, Settings or the playback queue)
     */
    public List<BrowseSection> getVideoSections() {
        List<BrowseSection> result = new ArrayList<>();

        for (BrowseSection section : mSections) { // contains sections and pinned items!
            int sectionId = section.getId();

            if (section.isEnabled() && sectionId != MediaGroup.TYPE_CHANNEL_UPLOADS &&
                    (mRowMapping.containsKey(sectionId) || mGridMapping.containsKey(sectionId))) {
                result.add(section);
            }
        }

        return result;
    }

    /**
     * The rows of a section from {@link #getVideoSections}, in parts. A grid is one row, only its first page.
     */
    @Nullable
    public Observable<List<MediaGroup>> getSectionContentObserve(int sectionId) {
        Observable<List<MediaGroup>> rows = mRowMapping.get(sectionId);

        if (rows != null) {
            return rows;
        }

        Observable<MediaGroup> grid = mGridMapping.get(sectionId);

        return grid != null ? grid.map(Collections::singletonList) : null;
    }

    private BrowseSection findSectionById(int sectionId) {
        for (BrowseSection section : mErrorSections) {
            if (section.getId() == sectionId) {
                return section;
            }
        }

        for (BrowseSection section : mSections) {
            if (section.getId() == sectionId) {
                return section;
            }
        }

        return null;
    }

    private int findSectionIndex(int sectionId) {
        if (sectionId == -1) {
            return -1;
        }

        int sectionIndex = -1;

        for (BrowseSection section : mErrorSections) {
            if (section.isEnabled()) {
                sectionIndex++;
                if (section.getId() == sectionId) {
                    return sectionIndex;
                }
            }
        }

        for (BrowseSection section : mSections) {
            if (section.isEnabled()) {
                sectionIndex++;
                if (section.getId() == sectionId) {
                    return sectionIndex;
                }
            }
        }

        return -1;
    }

    private BrowseSection findNearestSection(int sectionId) {
        BrowseSection result = findNearestSection(mErrorSections, sectionId);

        if (result == null) {
            result = findNearestSection(mSections, sectionId);
        }

        return result;
    }

    private BrowseSection findNearestSection(List<BrowseSection> sections, int sectionId) {
        BrowseSection result = null;
        BrowseSection previousSection = null;
        boolean found = false;
        for (BrowseSection section : sections) {
            if (section.getId() == sectionId) {
                found = true;
                continue;
            }
            if (section.isEnabled()) {
                if (found) {
                    result = section;
                    break;
                }
                previousSection = section;
            }
        }

        return result != null ? result : previousSection;
    }

    private void filterHomeIfNeeded(List<MediaGroup> mediaGroups) {
        if (mediaGroups == null || !isHomeSection()) {
            return;
        }

        // Not a row added to Home, e.g. a channel with News in its name
        Helpers.removeIf(mediaGroups, value -> !mAddedHomeRows.containsKey(value) && (Helpers.containsAny(
                value.getTitle(),
                "Primetime", // Free movies and shows row
                "News", // Top news
                "news", // Top news
                "NBA TV", // Sports
                "The Life of a Showgirl", // Taylor Swift ADS
                "FIFA", // Sports (FIFA World Cup 2026™)
                "FORMULA 1" // Sports (FORMULA 1 BRITISH GRAND PRIX)
        ) || Helpers.equalsAny(
                value.getTitle(),
                //getContext().getString(R.string.news_row_name),
                getContext().getString(R.string.breaking_news_row_name),
                getContext().getString(R.string.covid_news_row_name)
        )));
    }

    private Observable<MediaGroup> createPinnedGridAction(Video item) {
        if (item.channelGroupId != null) {
            return getContentService().getChannelFeedObserve(ChannelGroupServiceWrapper.instance(getContext()).findChannelIdsForGroup(item.channelGroupId));
        }

        return ChannelUploadsPresenter.instance(getContext()).obtainUploadsObservable(item);
    }

    private Observable<List<MediaGroup>> createPinnedRowAction(Video item) {
        return ChannelPresenter.instance(getContext()).obtainChannelObservable(item.channelId);
    }

    /**
     * Is Channels new look enabled?
     */
    public boolean isMultiGridChannelUploadsSection() {
        return mCurrentSection != null && mCurrentSection.getType() == BrowseSection.TYPE_MULTI_GRID && mCurrentSection.getId() == MediaGroup.TYPE_CHANNEL_UPLOADS;
    }

    public boolean isSettingsSection() {
        return isSection(MediaGroup.TYPE_SETTINGS);
    }

    public boolean isPlaylistsSection() {
        return isSection(MediaGroup.TYPE_USER_PLAYLISTS);
    }

    public boolean isHomeSection() {
        return isSection(MediaGroup.TYPE_HOME);
    }

    public boolean isHistorySection() {
        return isSection(MediaGroup.TYPE_HISTORY);
    }

    public boolean isWatchLaterSection() {
        return isSection(MediaGroup.TYPE_WATCH_LATER);
    }

    public boolean isSubscriptionsSection() {
        return isSection(MediaGroup.TYPE_SUBSCRIPTIONS);
    }
    
    public boolean isPlaybackQueueSection() {
        return isSection(MediaGroup.TYPE_PLAYBACK_QUEUE);
    }

    public boolean isPinnedSection() {
        return mCurrentSection != null && isPinnedId(mCurrentSection.getId());
    }

    private boolean isPinnedId(int id) {
        return id > 100;
    }

    private boolean isSection(int sectionId) {
        return mCurrentSection != null && mCurrentSection.getId() == sectionId;
    }

    public void selectSection(int sectionId) {
        getViewManager().startView(BrowseView.class); // focus view

        if (getView() == null) {
            mBootstrapSectionId = sectionId;
            return;
        }

        int sectionIndex = findSectionIndex(sectionId);

        if (sectionIndex == -1) {
            enableSection(sectionId, true);
            sectionIndex = findSectionIndex(sectionId);
            getSidebarService().enableSection(sectionId, false); // enable temporally (till restart)
        }

        if (sectionIndex != -1) {
            getView().selectSection(sectionIndex, true);
        }
    }

    public boolean inForeground() {
        return getViewManager().getTopView() == BrowseView.class;
    }

    private boolean isGridSection() {
        return mCurrentSection != null && mCurrentSection.getType() != BrowseSection.TYPE_ROW;
    }

    /**
     * Another u-tubot backend or token: the Processed section's cache is of the old connection and its user, so it can't be
     * replayed under the new one. An in-flight cached refresh is cancelled, so it can't show or write the old answer.
     */
    private void onUtubotConnectionChanged() {
        if (mBrowseCache == null || getContext() == null) {
            return;
        }

        BrowseSection processed = Helpers.findFirst(mSectionsMapping.values(), section -> section.getId() == UtubotProcessedSection.ID);

        if (processed == null) {
            return;
        }

        boolean inFlight = mCachedRefreshStarted && mCurrentSection != null && mCurrentSection.getId() == processed.getId();

        if (inFlight) {
            disposeActions();
        }

        invalidateCachedSection(processed);
    }

    @Override
    public void onAccountChanged(Account account) {
        Log.d(TAG, "On account changed");

        // An in-flight cached refresh would save the rows of the old account (or remove its stale ones) after the cache is cleared
        disposeActions();

        if (mBrowseCache != null) {
            mBrowseCache.invalidate();
        }

        discardCachedState();

        if (getView() == null) {
            return;
        }

        initSectionMappings();
        updateChannelSorting();
        updatePlaylistsStyle();
        updateSections();
    }

    public Video getCurrentVideo() {
        return mCurrentVideo;
    }

    private void initPasswordSection() {
        AccountsData accountsData = AccountsData.instance(getContext());
        if (accountsData.getAccountPassword() == null || accountsData.isPasswordAccepted()) {
            return;
        }

        mSections.clear();
        appendToSections(getContext().getString(R.string.header_notifications), R.drawable.icon_notification, new PasswordError(getContext()));
    }

    private void createPinnedMapping(Video item) {
        if (enableRows(item)) {
            mRowMapping.put(item.getId(), createPinnedRowAction(item));
        } else {
            mGridMapping.put(item.getId(), createPinnedGridAction(item));
        }
    }

    private BrowseSection createPinnedSection(Video item) {
        return new BrowseSection(
                item.getId(), item.getTitle(), enableRows(item) ? BrowseSection.TYPE_ROW : BrowseSection.TYPE_GRID, R.drawable.icon_pin, item.getCardImageUrl(), false, item);
    }

    private boolean enableRows(Video item) {
        return getMainUIData().isPinnedChannelRowsEnabled() && item.hasChannel() && !item.isPlaylistAsChannel();
    }

    private void handleLoadError(Throwable error) {
        if (getView() == null) {
            return;
        }

        getView().showProgressBar(false);
        getView().showRefreshing(false);

        if (getView().isEmpty() || error != null) {
            ErrorFragmentData errorFragmentData;
            if (error != null && !Helpers.containsAny(error.getMessage(), "fromNullable result is null")) {
                errorFragmentData = new CategoryEmptyError(getContext(), error);
            } else if (getSignInService().isSigned()) {
                errorFragmentData = new CategoryEmptyError(getContext(), null);
            } else {
                errorFragmentData = new SignInError(getContext());
            }

            getView().showError(errorFragmentData);

            if (Utils.fixRetrofitErrors(getContext(), error) || mIsChannelContent) {
                return;
            }

            Utils.postDelayed(mRefreshSection, 30_000);
        }
    }

    /**
     * The rows of History of the videos watched here (see appendLocalHistory), when the account has none to show: signed out,
     * or a history with no video. Like the rows of the account: the videos, then the shorts. The videos alone with
     * Hide Shorts History, in the grid.
     */
    private void updateLocalHistoryRows() {
        getView().showProgressBar(false);

        VideoGroup clear = VideoGroup.from(getCurrentSection());
        clear.setAction(VideoGroup.ACTION_REPLACE);
        getView().updateSection(clear);

        addLocalHistoryRow(0, false, true);

        if (!isShortsHistoryHidden()) {
            addLocalHistoryRow(1, true, true);
        }
    }

    /**
     * The row of History the account's history has none for, when the videos of its kind watched here aren't in it (see
     * appendLocalHistory): the row of videos on top, the row of shorts under it
     */
    private void addMissingLocalHistoryRows(List<VideoGroup> rows) {
        if (!isHistorySection()) {
            return;
        }

        boolean hasVideosRow = false;
        boolean hasShortsRow = false;

        for (VideoGroup row : rows) {
            if (isShortsRow(row)) {
                hasShortsRow = true;
            } else {
                hasVideosRow = true;
            }
        }

        if (!hasVideosRow) {
            addLocalHistoryRow(0, false, false);
        }

        if (!hasShortsRow) {
            addLocalHistoryRow(1, true, false);
        }
    }

    /**
     * A row with no video isn't added
     */
    private void addLocalHistoryRow(int position, boolean isShortsRow, boolean isHistoryEmpty) {
        VideoGroup row = VideoGroup.from(getCurrentSection(), position);
        // As the rows of the account (see createRowGroups)
        row.setTitle(getContext().getString(isShortsRow ? R.string.history_shorts : R.string.history_videos));

        appendLocalHistory(row, isShortsRow, isHistoryEmpty);
        getView().updateSection(row);
    }

    /**
     * The row of shorts of History (see ContentService.getHistoryRows)
     */
    private static boolean isShortsRow(VideoGroup videoGroup) {
        MediaGroup mediaGroup = videoGroup.getMediaGroup();

        return mediaGroup != null && mediaGroup.getRowKind() == MediaGroup.ROW_KIND_SHORTS;
    }

    /**
     * The videos watched here on top of the row of History of their kind: the shorts on the row of shorts, the others on the row of
     * videos. The ones of this launch when the account's history hasn't got them (see VideoStateService.isHistoryBroken), all of them
     * when it has no video.<br/>
     * A video kept from an earlier launch isn't known to be a short (see Video.toString): it's on the row of videos.
     *
     * @param isHistoryEmpty the account's History has no video (e.g. signed out)
     */
    private void appendLocalHistory(VideoGroup videoGroup, boolean isShortsRow, boolean isHistoryEmpty) {
        if (!isHistorySection()) {
            return;
        }

        VideoStateService stateService = VideoStateService.instance(getContext());

        if (stateService.isEmpty() || (!isHistoryEmpty && !stateService.isHistoryBroken())) {
            return;
        }

        List<State> states = new ArrayList<>();

        for (State state : stateService.getStates()) {
            if (state.video.isShorts == isShortsRow) {
                states.add(state);
            }
        }

        if (states.isEmpty()) {
            return;
        }

        Video lastHistoryItem = videoGroup.isEmpty() ? null : videoGroup.get(0);
        State lastState = states.get(states.size() - 1);

        if (Helpers.equals(lastHistoryItem, lastState.video)) {
            return;
        }

        for (State state : states) {
            if (isHistoryEmpty || state.timestamp > stateService.getSessionStartTimeMs()) {
                videoGroup.add(0, state.video);
            }
        }
    }
}
