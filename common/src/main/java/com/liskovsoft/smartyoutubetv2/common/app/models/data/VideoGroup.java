package com.liskovsoft.smartyoutubetv2.common.app.models.data;

import com.liskovsoft.mediaserviceinterfaces.data.ChapterItem;
import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.prefs.GlobalPreferences;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService.State;
import com.liskovsoft.smartyoutubetv2.common.misc.AiSListManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.misc.ChannelGroupFilter;
import com.liskovsoft.smartyoutubetv2.common.misc.ChildModeManager;
import com.liskovsoft.smartyoutubetv2.common.misc.DuplicateFilter;
import com.liskovsoft.smartyoutubetv2.common.misc.KeywordFilter;
import com.liskovsoft.smartyoutubetv2.common.misc.CollaborationManager;
import com.liskovsoft.smartyoutubetv2.common.misc.NotInterestedManager;
import com.liskovsoft.smartyoutubetv2.common.misc.OldVideoFilter;
import com.liskovsoft.smartyoutubetv2.common.misc.ShortsDateManager;
import com.liskovsoft.smartyoutubetv2.common.misc.VideoCategoryManager;
import com.liskovsoft.smartyoutubetv2.common.misc.StreamedManager;
import com.liskovsoft.smartyoutubetv2.common.misc.WatchLaterManager;
import com.liskovsoft.smartyoutubetv2.common.prefs.AiSListFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.BlockedChannelData;
import com.liskovsoft.smartyoutubetv2.common.prefs.ChannelGroupFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.ExploreTopicsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.FilterExclusionData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HiddenVideosData;
import com.liskovsoft.smartyoutubetv2.common.prefs.HomeRowsData.Row;
import com.liskovsoft.smartyoutubetv2.common.prefs.KeywordFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.OpenedVideosData;
import com.liskovsoft.smartyoutubetv2.common.prefs.SectionFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.ShowsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.StreamedData;
import com.liskovsoft.smartyoutubetv2.common.prefs.TopChannelsData;
import com.liskovsoft.smartyoutubetv2.common.utils.CompactInfo;

import java.util.ArrayList;
import java.util.Collections;
import java.util.ConcurrentModificationException;
import java.util.List;

public class VideoGroup {
    /**
     * Add at the end of the existing group
     */
    public static final int ACTION_APPEND = 0;
    /**
     * Clear whole fragment and then add this group
     */
    public static final int ACTION_REPLACE = 1;
    public static final int ACTION_REMOVE = 2;
    public static final int ACTION_REMOVE_AUTHOR = 3;
    public static final int ACTION_SYNC = 4;
    /**
     * Add at the begin of the existing group
     */
    public static final int ACTION_PREPEND = 5;
    private static final String TAG = VideoGroup.class.getSimpleName();
    private static final float WATCHED_PERCENT = 80; // as Hide watched videos from Subscriptions (see MediaGroupOptions of MediaServiceCore)
    private int mId;
    private String mTitle;
    private List<Video> mVideos;
    private MediaGroup mMediaGroup;
    private BrowseSection mSection;
    private int mPosition = -1;
    private int mAction = ACTION_APPEND;
    private int mType = -1;
    private int mHiddenVideoCount;
    private int mDuplicateCount;
    private DuplicateFilter mDuplicateFilter; // the videos of the rows above, also for the pages added later
    private boolean mIsChannelRow; // every item is a channel (see MediaGroup.isChannelRow), kept by the pages added later
    private boolean mIsSearchTopicRow; // every item is a topic that opens a search (see MediaGroup.isSearchTopicRow), kept by the pages added later
    private int mAddedHomeRowType = -1; // a row added to Home (see HomeRowsData.Row.type), kept by the pages added later
    private int mHiddenFromSection = MediaGroup.TYPE_UNDEFINED; // a row of the Unhide section: where its videos were hidden from
    public boolean isQueue;

    public static VideoGroup from(BrowseSection section) {
        return from((MediaGroup) null, section);
    }

    public static VideoGroup from(MediaGroup mediaGroup) {
        return from(mediaGroup, (BrowseSection) null);
    }

    public static VideoGroup from(BrowseSection section, int groupPosition) {
        return from((MediaGroup) null, section, groupPosition);
    }

    public static VideoGroup from(MediaGroup mediaGroup, BrowseSection section) {
        return from(mediaGroup, section, -1);
    }

    public static VideoGroup from(Video item) {
        return from(item, extractGroupPosition(item));
    }

    public static VideoGroup from(Video item, int groupPosition) {
        return from(new ArrayList<>(Collections.singletonList(item)), null, groupPosition);
    }

    public static VideoGroup from(List<Video> items) {
        return from(items, null);
    }

    public static VideoGroup from(List<Video> items, BrowseSection section) {
        return from(items, section, extractGroupPosition(items));
    }

    public static VideoGroup from(List<Video> items, BrowseSection section, int groupPosition) {
        VideoGroup videoGroup = new VideoGroup();
        // Getting topmost element. Could help when syncing multi rows fragments.
        Video topItem = findTopmostItemWithGroup(items);
        if (topItem != null && topItem.getGroup() != null) {
            videoGroup.mId = topItem.getGroup().getId();
            videoGroup.mTitle = topItem.getGroup().getTitle();
        }
        videoGroup.mVideos = items;
        videoGroup.mPosition = groupPosition;
        videoGroup.mSection = section;

        for (Video item : items) {
            // Section as playlist fix. Don't change the root.
            if (item.getGroup() == null || section != null) {
                item.setGroup(videoGroup);
            }
        }

        return videoGroup;
    }

    public static VideoGroup from(MediaGroup mediaGroup, BrowseSection section, int groupPosition) {
        return from(mediaGroup, section, groupPosition, null);
    }

    /**
     * @param duplicateFilter the videos of the rows above, left out of the row and of its next pages, or null to keep them
     */
    public static VideoGroup from(MediaGroup mediaGroup, BrowseSection section, int groupPosition, DuplicateFilter duplicateFilter) {
        return from(mediaGroup, section, groupPosition, duplicateFilter, null);
    }

    /**
     * @param duplicateFilter the videos of the rows above, left out of the row and of its next pages, or null to keep them
     * @param addedHomeRow the row of Home it is when it's one added to Home (see HomeRowsData), or null
     */
    public static VideoGroup from(MediaGroup mediaGroup, BrowseSection section, int groupPosition, DuplicateFilter duplicateFilter,
                                  Row addedHomeRow) {
        VideoGroup videoGroup = new VideoGroup();
        videoGroup.mSection = section;
        videoGroup.mPosition = groupPosition;
        videoGroup.mVideos = new ArrayList<>();
        videoGroup.mMediaGroup = mediaGroup;
        videoGroup.mTitle = mediaGroup != null && mediaGroup.getTitle() != null ?
                mediaGroup.getTitle() : section != null ? section.getTitle() : null;
        // Fix duplicated rows e.g. Shorts
        //videoGroup.mId = !TextUtils.isEmpty(videoGroup.mTitle) ? videoGroup.mTitle.hashCode() : videoGroup.hashCode();
        videoGroup.mId = videoGroup.hashCode();
        videoGroup.mDuplicateFilter = duplicateFilter;

        if (mediaGroup == null) {
            return videoGroup;
        }

        // Before the items: they're marked or hidden by it
        videoGroup.mIsChannelRow = mediaGroup.isChannelRow();
        videoGroup.mIsSearchTopicRow = mediaGroup.isSearchTopicRow();
        videoGroup.mAddedHomeRowType = addedHomeRow != null ? addedHomeRow.type : -1;
        // E.g. the watched videos of Hide watched videos from Home
        videoGroup.mHiddenVideoCount = mediaGroup.getFilteredVideoCount();

        if (mediaGroup.getMediaItems() == null) {
            Log.e(TAG, "MediaGroup doesn't contain media items. Title: " + mediaGroup.getTitle());
            return videoGroup;
        }

        for (MediaItem item : mediaGroup.getMediaItems()) {
            Video video = Video.from(item);

            videoGroup.add(video);
        }

        return videoGroup;
    }

    public static VideoGroup from(VideoGroup baseGroup, MediaGroup mediaGroup) {
        baseGroup.mMediaGroup = mediaGroup;

        if (mediaGroup == null) {
            return baseGroup;
        }

        baseGroup.mHiddenVideoCount += mediaGroup.getFilteredVideoCount();

        if (mediaGroup.getMediaItems() == null) {
            Log.e(TAG, "MediaGroup doesn't contain media items. Title: " + mediaGroup.getTitle());
            return baseGroup;
        }

        for (MediaItem item : mediaGroup.getMediaItems()) {
            Video video = Video.from(item);

            baseGroup.add(video);
        }

        baseGroup.mAction = ACTION_APPEND;

        return baseGroup;
    }

    public static VideoGroup from(VideoGroup baseGroup, VideoGroup newGroup) {
        baseGroup.mMediaGroup = newGroup.mMediaGroup;

        if (newGroup.mMediaGroup == null) {
            return baseGroup;
        }

        if (newGroup.getVideos() == null) {
            Log.e(TAG, "MediaGroup doesn't contain media items. Title: " + newGroup.getTitle());
            return baseGroup;
        }

        for (Video video : newGroup.getVideos()) {
            baseGroup.add(video);
        }

        baseGroup.mAction = ACTION_APPEND;

        return baseGroup;
    }

    public static VideoGroup fromChapters(List<ChapterItem> chapters, String title) {
        VideoGroup videoGroup = new VideoGroup();
        videoGroup.mTitle = title;
        videoGroup.mVideos = new ArrayList<>();

        for (ChapterItem chapter : chapters) {
            Video video = Video.from(chapter);

            videoGroup.add(video);
        }

        return videoGroup;
    }

    public List<Video> getVideos() {
        // NOTE: Don't make the collection read only
        // The collection will be filtered inside VideoGroupObjectAdapter
        return Collections.unmodifiableList(mVideos);
    }

    public String getTitle() {
        return mTitle;
    }

    /**
     * The title is converted to unique row id.
     */
    public void setTitle(String title) {
        mTitle = title;

        //if (!TextUtils.isEmpty(title) && (mId == 0 || mId == hashCode())) {
        //    mId = title.hashCode();
        //}
    }

    public int getId() {
        return mId;
    }

    public void setId(int id) {
        mId = id;
    }

    public MediaGroup getMediaGroup() {
        return mMediaGroup;
    }

    public BrowseSection getSection() {
        return mSection;
    }

    public boolean isShorts() {
        if (isEmpty()) {
            return false;
        }

        for (int i = 0; i < Math.min(8, mVideos.size()); i++) {
             if (!mVideos.get(i).isShorts)
                 return false;
        }

        return true;
    }

    public boolean isChapters() {
        return !isEmpty() && mVideos.get(0).isChapter;
    }

    /**
     * Group position in multi-grid fragments<br/>
     * It isn't used on other types of fragments.
     */
    public int getPosition() {
        return mPosition;
    }

    public void setPosition(int position) {
        mPosition = position;
    }

    public int getAction() {
        return mAction;
    }

    public void setAction(int action) {
        mAction = action;

        if (action == ACTION_PREPEND) {
            mPosition = 0;
        }
    }

    public int getType() {
        return mType != -1 ? mType : getMediaGroup() != null ? getMediaGroup().getType() : mSection != null ? mSection.getId() : -1;
    }

    public void setType(int type) {
        mType = type;
    }

    public String getReloadPageKey() {
        MediaGroup mediaGroup = getMediaGroup(); // read once: the history is written off the main thread
        return mediaGroup != null ? mediaGroup.getReloadPageKey() : null;
    }

    public String getNextPageKey() {
        return getMediaGroup() != null ? getMediaGroup().getNextPageKey() : null;
    }

    /**
     * Lightweight copy (without nested videos)
     */
    public VideoGroup copy() {
        VideoGroup videoGroup = new VideoGroup();
        videoGroup.mId = mId;
        videoGroup.mTitle = mTitle;
        videoGroup.mPosition = mPosition;

        return videoGroup;
    }

    /**
     * Getting topmost element. Could help when syncing multi rows fragments.
     */
    private static Video findTopmostItemWithGroup(List<Video> items) {
        if (items.isEmpty()) {
            return null;
        }

        for (int i = (items.size() - 1); i >= 0; i--) {
            Video video = items.get(i);
            if (video.getGroup() != null) {
                return video;
            }
        }

        return items.get(items.size() - 1); // No group. Fallback to last item then.
    }

    private static int extractGroupPosition(List<Video> items) {
        if (items == null || items.isEmpty()) {
            return -1;
        }

        return extractGroupPosition(findTopmostItemWithGroup(items));
    }

    private static int extractGroupPosition(Video item) {
        int groupPosition = -1;

        if (item != null) {
            groupPosition = item.groupPosition;
        }

        return groupPosition;
    }

    public void removeAllBefore(Video video) {
        if (mVideos == null) {
            return;
        }

        removeAllBefore(mVideos.indexOf(video));
    }

    public void removeAllBefore(int index) {
        if (mVideos == null) {
            return;
        }

        if (index <= 0 || index >= mVideos.size()) {
            return;
        }

        mVideos = mVideos.subList(index, mVideos.size());
    }

    /**
     * Remove playlist id from all videos
     */
    public void stripPlaylistInfo() {
        if (mVideos == null) {
            return;
        }

        for (Video video : mVideos) {
            video.playlistId = null;
            video.remotePlaylistId = null;
        }
    }

    public Video findVideoById(String videoId) {
        if (mVideos == null) {
            return null;
        }

        Video result = null;

        for (Video video : mVideos) {
            if (Helpers.equals(videoId, video.videoId)) {
                result = video;
                break;
            }
        }

        return result;
    }

    public void clear() {
        if (mVideos == null) {
            return;
        }

        mVideos.clear();
    }

    public boolean contains(Video video) {
        if (mVideos == null) {
            return false;
        }

        return mVideos.contains(video);
    }

    public int getSize() {
        if (mVideos == null) {
            return -1;
        }

        return mVideos.size();
    }

    public int indexOf(Video video) {
        if (mVideos == null) {
            return -1;
        }

        return mVideos.indexOf(video);
    }

    public Video get(int idx) {
        if (mVideos == null) {
            return null;
        }

        return mVideos.get(idx);
    }

    public void remove(Video video) {
        if (mVideos == null) {
            return;
        }

        try {
            // ConcurrentModificationException fix?
            mVideos.remove(video);
        } catch (UnsupportedOperationException | ConcurrentModificationException e) { // read only collection
            e.printStackTrace();
        }
    }

    /**
     * The videos left out because the rows above, or this one, have them (see DuplicateFilter). Also counted as hidden.
     */
    public int getDuplicateCount() {
        return mDuplicateCount;
    }

    /**
     * Every video was hidden, here or by the service (see MediaGroup.getFilteredVideoCount), and only cards without a video are left
     * (e.g. "More music" of a music row, or of "Listen again" with Hide watched videos from Home)
     */
    public boolean hasOnlyHiddenVideos() {
        if (mHiddenVideoCount == 0 || isEmpty()) {
            return false;
        }

        for (Video video : mVideos) {
            if (video.videoId != null) {
                return false;
            }
        }

        return true;
    }

    public boolean isEmpty() {
        try {
            return mVideos == null || mVideos.isEmpty();
        } catch (ConcurrentModificationException e) {
            e.printStackTrace();
        }

        return true;
    }

    public void add(Video video) {
        // TODO: remove the hack someday.
        // Dirty hack for avoiding group duplication.
        // Duplicated items suddenly appeared in Home, Subscriptions and History.
        // See: VideoGroupObjectAdapter.mVideoItems
        if (mVideos != null && mVideos.contains(video)) {
            return;
        }

        int size = getSize();
        add(size != -1 ? size : 0, video);
    }

    public void add(int idx, Video video) {
        if (video == null || video.isEmpty()) {
            return;
        }

        addShortsDate(video);

        if (isChannelBlocked(video) || isNotInterested(video) || isHiddenWithMenu(video) || isAiListed(video) || isHiddenCategory(video) || isOld(video) || isHiddenCollaboration(video)
                || isHiddenWatchLater(video) || isHiddenShow(video) || isHiddenStreamed(video) || isHiddenTopChannel(video) || isHiddenExploreTopic(video)
                || hasHiddenKeyword(video) || isWatchedSuggestion(video) || isUnsubscribedChannel(video) || isHiddenChannelGroupChannel(video)
                || isWatchedInChannelGroup(video) || isHiddenOpened(video) || isHiddenByUtubot(video) || isDuplicate(video)) {
            if (video.videoId != null) {
                mHiddenVideoCount++;
            }

            return;
        }

        if (mVideos == null) {
            mVideos = new ArrayList<>();
        }

        // Group position in multi-grid fragments
        video.groupPosition = mPosition;
        video.setGroup(this);

        VideoStateService stateService = VideoStateService.instance(null);
        // Keep remote completion when an older local playback position exists.
        if (stateService != null && video.percentWatched == -1) {
            State state = stateService.getByVideoId(video.videoId);
            video.sync(state);
        }

        mVideos.add(idx, video);
    }

    private boolean isChannelBlocked(Video video) {
        if (video.isChapter) {
            return false;
        }

        BlockedChannelData blockedChannelData = BlockedChannelData.instance(GlobalPreferences.context());

        if (blockedChannelData.isEmpty()) {
            return false;
        }

        // Filter out videos from blacklisted channels
        String channelId = video.channelId;
        String channelName = video.getAuthor();

        return blockedChannelData.containsChannel(channelId, channelName);
    }

    /**
     * Marked "Not interested", or its channel "Don't recommend channel", in the app (see NotInterestedManager).
     * In the sections that offer them and in the player's suggestions, but not in the playlist that plays there.
     */
    public boolean isNotInterested(Video video) {
        int type = getType();

        if (!Video.isHomeLikeType(type) && type != MediaGroup.TYPE_SHORTS && type != MediaGroup.TYPE_SUGGESTIONS) {
            return false;
        }

        if (type == MediaGroup.TYPE_SUGGESTIONS && video.playlistId != null) {
            return false;
        }

        return NotInterestedManager.instance().isHidden(video);
    }

    /**
     * Hidden from the section with the Hide of the context menu (see HiddenVideosData)
     */
    private boolean isHiddenWithMenu(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (!isHideableCard(video) || GlobalPreferences.context() == null) {
            return false;
        }

        HiddenVideosData data = HiddenVideosData.instance(GlobalPreferences.context());

        return !data.isEmpty() && data.isHidden(getHiddenVideosSection(), video.videoId);
    }

    /**
     * Gone from the menu after it was added: marked "Not interested" or hidden with Hide. The other rows that have it let it go
     * too (see VideoGroupObjectAdapter.removeNotInterested).
     */
    public boolean isRemovedWithMenu(Video video) {
        return isNotInterested(video) || isHiddenWithMenu(video);
    }

    /**
     * A card the Hide of the context menu hides: a video. Not a playlist (its video id is the first video's), a show, a channel
     * or a chapter.
     */
    public static boolean isHideableCard(Video video) {
        return video != null && video.videoId != null && !video.isChapter && !video.isShow && !video.isPlaylistAsChannel()
                && video.itemType != MediaItem.TYPE_PLAYLIST && video.itemType != MediaItem.TYPE_CHANNEL;
    }

    /**
     * The section a video is hidden from with the context menu (see HiddenVideosData): the sidebar section, all the subscription
     * groups as one (their sections and their rows of Home), Subscriptions for its row of Home too, then search, the channel pages
     * or the player's suggestions. MediaGroup.TYPE_UNDEFINED elsewhere (e.g. a playlist page).
     */
    public int getHiddenVideosSection() {
        if (isChannelGroup()) {
            return SectionFilterData.SECTION_CHANNEL_GROUPS;
        }

        if (mAddedHomeRowType == Row.TYPE_SUBSCRIPTIONS) {
            return MediaGroup.TYPE_SUBSCRIPTIONS;
        }

        if (getSection() != null) {
            return getSection().getId();
        }

        if (getType() == MediaGroup.TYPE_SUGGESTIONS) {
            return MediaGroup.TYPE_SUGGESTIONS;
        }

        // Search, a channel page, otherwise none
        return getFilterSectionId();
    }

    /**
     * A row of the Unhide section: the section its videos were hidden from (see HiddenVideosData), otherwise MediaGroup.TYPE_UNDEFINED
     */
    public int getHiddenFromSection() {
        return mHiddenFromSection;
    }

    public void setHiddenFromSection(int sectionId) {
        mHiddenFromSection = sectionId;
    }

    /**
     * Also marks the video when the marking is enabled instead of hiding. A channel card is only marked.
     */
    private boolean isAiListed(Video video) {
        boolean isChannel = isChannelCard(video);

        // Chapters aren't filtered, nor the cards of neither a video nor a channel (e.g. a playlist)
        if (video.isChapter || (video.videoId == null && !isChannel)) {
            return false;
        }

        int section = getAiSListSection();
        AiSListManager manager = AiSListManager.instance(GlobalPreferences.context());

        if (!manager.isSectionEnabled(section)) {
            return false;
        }

        if (video.channelHandle == null) {
            // Most TV cards have only the channel name, a collaboration the names of its channels. The handles are looked up
            // by a video before the group is created (see HiddenVideoResolver). A channel card has no video: its name was seen on one.
            video.channelHandle = manager.getCachedHandle(AiSListManager.getLookupKey(video), section);
        }

        if (video.channelHandle == null) {
            return false;
        }

        if (isChannel) {
            video.aiMarkList = manager.getChannelMarkedList(video.channelHandle, section);
            return false;
        }

        if (manager.isHidden(video.channelHandle, section)) {
            manager.onHidden(video);
            return true;
        }

        video.aiMarkList = manager.getMarkedList(video.channelHandle, section);

        return false;
    }

    /**
     * A card that opens a channel (e.g. in Top channels you watch, a channel search result or the channels of the Channels section).
     * Not a show or a playlist, which open like a channel.
     */
    private static boolean isChannelCard(Video video) {
        return video.videoId == null && !video.isShow && !video.isPlaylistAsChannel() && (video.isChannel() || video.hasNestedItems());
    }

    /**
     * The categories are looked up before the group is created (see VideoCategoryManager).
     * Also marks the video with the categories set to mark instead of hiding.
     */
    private boolean isHiddenCategory(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || GlobalPreferences.context() == null) {
            return false;
        }

        VideoCategoryManager manager = VideoCategoryManager.instance(GlobalPreferences.context());

        if (!manager.isGroupEnabled(getType())) {
            return false;
        }

        if (manager.isVideoHidden(video.videoId, getType())) {
            return true;
        }

        video.categoryMarks = manager.getMarks(video.videoId, getType());

        return false;
    }

    /**
     * The date of a short that comes without it, looked up before the group is created (see ShortsDateManager).
     * Before the filters: Hide old videos reads it too.
     */
    private static void addShortsDate(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || GlobalPreferences.context() == null) {
            return;
        }

        ShortsDateManager.instance(GlobalPreferences.context()).addDate(video);
    }

    /**
     * A channel in a subscription group, in the areas picked for them (see ChannelGroupFilter). A channel card is left alone.
     */
    private boolean isHiddenChannelGroupChannel(Video video) {
        int area = getChannelGroupFilterArea();

        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || area == -1 || GlobalPreferences.context() == null) {
            return false;
        }

        return ChannelGroupFilter.isHidden(GlobalPreferences.context(), area, video.channelId, video.getAuthor());
    }

    /**
     * Where the group is for ChannelGroupFilterData: the Subscriptions row added to Home, otherwise the section.
     * None for the other rows added to Home (e.g. the row of a group would hide its own channels) or out of the sections.
     */
    private int getChannelGroupFilterArea() {
        if (mAddedHomeRowType == Row.TYPE_SUBSCRIPTIONS) {
            return ChannelGroupFilterData.AREA_HOME_SUBSCRIPTIONS_ROW;
        }

        if (mAddedHomeRowType != -1 || getSection() == null) {
            return -1;
        }

        return getSection().getId();
    }

    /**
     * Watched, in the section of a subscription group or its row of Home, while the watched videos are hidden from the groups.
     * Watched as YouTube's card has it or as the app played it (see VideoStateService). A live stream is left alone.
     */
    private boolean isWatchedInChannelGroup(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || video.isLive || !isChannelGroup() || GlobalPreferences.context() == null
                || !ChannelGroupFilterData.instance(GlobalPreferences.context()).isWatchedHidden()) {
            return false;
        }

        return video.percentWatched > WATCHED_PERCENT || getPercentWatchedInApp(video) > WATCHED_PERCENT;
    }

    /**
     * Has progress on it, however little, as YouTube's card has it or as the app played it (see VideoStateService), while the
     * opened videos are hidden (see OpenedVideosData). Only in the feeds (see isOpenedVideoSection). A live stream is left alone.
     */
    private boolean isHiddenOpened(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || video.isLive || GlobalPreferences.context() == null
                || !OpenedVideosData.instance(GlobalPreferences.context()).isHidden() || !isOpenedVideoSection()) {
            return false;
        }

        State state = getStateInApp(video);

        return video.percentWatched > 0 || (state != null && state.positionMs > 0);
    }

    /**
     * The feeds: Home and the sections like it, Subscriptions, Channels, the subscription groups and Notifications, then search
     * and the channel pages. Not History, Watch later, the playlists, My videos or the player's suggestions.
     */
    private boolean isOpenedVideoSection() {
        switch (getAiSListSection()) {
            case AiSListFilterData.SECTION_HOME:
            case AiSListFilterData.SECTION_SEARCH:
            case AiSListFilterData.SECTION_SUBSCRIPTIONS:
            case AiSListFilterData.SECTION_CHANNELS:
            case AiSListFilterData.SECTION_CHANNEL_GROUPS:
            case AiSListManager.SECTION_CHANNEL_PAGE:
                return true;
            default:
                return getType() == MediaGroup.TYPE_NOTIFICATIONS;
        }
    }

    /**
     * The section of a subscription group (see BrowseSection.isChannelGroup) or its row added to Home
     */
    private boolean isChannelGroup() {
        return mAddedHomeRowType == Row.TYPE_CHANNEL_GROUP || (getSection() != null && getSection().isChannelGroup());
    }

    /**
     * As the card gets it below (see Video.sync), or -1 when the app hasn't played it
     */
    private static float getPercentWatchedInApp(Video video) {
        State state = getStateInApp(video);

        if (state == null) {
            return -1;
        }

        long durationMs = state.durationMs != -1 ? state.durationMs : video.getDurationMs();

        return durationMs > 0 ? state.positionMs / (durationMs / 100f) : -1;
    }

    /**
     * Where the app left the video when it played it, or null
     */
    private static State getStateInApp(Video video) {
        VideoStateService stateService = VideoStateService.instance(null);

        return stateService != null ? stateService.getByVideoId(video.videoId) : null;
    }

    /**
     * Older than the period of the Hide content setting, only in the sections picked there
     */
    private boolean isOld(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || getSection() == null || GlobalPreferences.context() == null) {
            return false;
        }

        return OldVideoFilter.isHidden(GlobalPreferences.context(), getSection().getId(), video.getSecondTitle());
    }

    /**
     * In Child mode, the card of a channel the account isn't subscribed to on a channel page (e.g. its featured channels).
     * It wouldn't open (see ChildModeManager).
     */
    private boolean isUnsubscribedChannel(Video video) {
        boolean isChannelCard = video.isChannel() || (video.videoId == null && video.itemType == MediaItem.TYPE_CHANNEL);

        // No context before the app is initialized (GlobalPreferences)
        if (getType() != MediaGroup.TYPE_CHANNEL || !isChannelCard || GlobalPreferences.context() == null) {
            return false;
        }

        return ChildModeManager.instance(GlobalPreferences.context()).isHidden(video.channelId);
    }

    /**
     * A collaboration, only in the sections picked in the Collaborations setting.
     * Also marks the video when the setting marks instead of hiding, or a channel of it is excluded from the hiding. The names are looked up before the group is created (see HiddenVideoResolver).
     */
    private boolean isHiddenCollaboration(Video video) {
        int sectionId = getFilterSectionId();

        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || sectionId == -1 || GlobalPreferences.context() == null) {
            return false;
        }

        String author = video.getAuthor();

        if (!CollaborationManager.isCandidate(author)) {
            return false;
        }

        CollaborationManager manager = CollaborationManager.instance(GlobalPreferences.context());

        if (!manager.isEnabled(sectionId) || !Boolean.TRUE.equals(manager.getCachedResult(author))) {
            return false;
        }

        if (manager.isHidden(sectionId) && !isExcludedCollaboration(video, author)) {
            return true;
        }

        video.isCollaboration = true;

        return false;
    }

    /**
     * In the account's Watch later, only in the sections picked in the Watch later setting.
     * Also marks the video when the setting marks instead of hiding, or its channel is excluded from the hiding. The list is read before the group is created (see HiddenVideoResolver).
     */
    private boolean isHiddenWatchLater(Video video) {
        int sectionId = getFilterSectionId();

        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || sectionId == -1 || GlobalPreferences.context() == null) {
            return false;
        }

        if (WatchLaterManager.isWatchLaterPlaylist(this, video)) {
            return false;
        }

        WatchLaterManager manager = WatchLaterManager.instance(GlobalPreferences.context());

        if (!manager.isEnabled(sectionId) || !manager.contains(video.videoId)) {
            return false;
        }

        if (manager.isHidden(sectionId) && !isExcludedChannel(FilterExclusionData.FILTER_WATCH_LATER, video)) {
            return true;
        }

        video.isInWatchLater = true;

        return false;
    }

    /**
     * A show (podcast), only in the sections picked in the Shows setting. Also marks the show when the setting marks instead of hiding.
     */
    private boolean isHiddenShow(Video video) {
        int sectionId = getFilterSectionId();

        // No context before the app is initialized (GlobalPreferences)
        if (!video.isShow || sectionId == -1 || GlobalPreferences.context() == null) {
            return false;
        }

        ShowsData data = ShowsData.instance(GlobalPreferences.context());

        if (!data.isEnabled(sectionId)) {
            return false;
        }

        if (data.isHidingEnabled(sectionId)) {
            return true;
        }

        video.isShowMarked = true;

        return false;
    }

    /**
     * A live stream that ended ("Streamed 5 hours ago") or one that's live now, only in the sections picked in the Streamed or Live setting.
     * Also marks the video when the setting marks instead of hiding, or its channel is excluded from the hiding. Only the English date
     * of a stream that ended is known (see CompactInfo.isStreamed). History cards come without the date: it's looked up before the group
     * is created (see StreamedManager). A stream to come is left alone.
     */
    private boolean isHiddenStreamed(Video video) {
        int sectionId = getFilterSectionId();

        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || video.isUpcoming || sectionId == -1 || GlobalPreferences.context() == null) {
            return false;
        }

        StreamedData data = StreamedData.instance(GlobalPreferences.context());

        if (!data.isEnabled(sectionId) || (!video.isLive && !isStreamed(video))) {
            return false;
        }

        if (data.isHidingEnabled(sectionId) && !isExcludedChannel(FilterExclusionData.FILTER_STREAMED, video)) {
            return true;
        }

        if (video.isLive) {
            video.isLiveMarked = true;
        } else {
            video.isStreamedMarked = true;
        }

        return false;
    }

    /**
     * The date on the card says it, or a lookup found it (see StreamedManager)
     */
    private static boolean isStreamed(Video video) {
        return CompactInfo.isStreamed(video.getSecondTitle()) || StreamedManager.instance(GlobalPreferences.context()).isStreamed(video.videoId);
    }

    /**
     * The channel of the video is excluded from the hiding of the filter (see FilterExclusionData): the video is marked instead
     * @param filter one of FilterExclusionData.FILTER_*
     */
    private static boolean isExcludedChannel(int filter, Video video) {
        return FilterExclusionData.instance(GlobalPreferences.context()).isExcluded(filter, video.channelId, video.getAuthor());
    }

    /**
     * Excluded as a whole or by one of its channels: the card only has "X and Y" (see CollaborationManager.getChannelNames)
     */
    private static boolean isExcludedCollaboration(Video video, String author) {
        if (isExcludedChannel(FilterExclusionData.FILTER_COLLABORATIONS, video)) {
            return true;
        }

        FilterExclusionData data = FilterExclusionData.instance(GlobalPreferences.context());

        for (String name : CollaborationManager.getChannelNames(author)) {
            if (data.isExcluded(FilterExclusionData.FILTER_COLLABORATIONS, null, name)) {
                return true;
            }
        }

        return false;
    }

    /**
     * A row of channels (e.g. Top channels you watch) or of topics (e.g. Explore more topics) that its setting hides.
     * It isn't shown or continued.
     */
    public boolean isHiddenRow() {
        return getTopChannelsMode() == SectionFilterData.MODE_HIDE || getExploreTopicsMode() == SectionFilterData.MODE_HIDE;
    }

    /**
     * A channel of a row of channels, hidden with its row. Also marks the channel when the setting marks instead of hiding.
     */
    private boolean isHiddenTopChannel(Video video) {
        int mode = getTopChannelsMode();

        if (mode == SectionFilterData.MODE_MARK) {
            video.isTopChannelMarked = true;
        }

        return mode == SectionFilterData.MODE_HIDE;
    }

    /**
     * The mode of the Top channels you watch setting for the row. Shown unless it's a row of channels of a section picked in the setting.
     */
    private int getTopChannelsMode() {
        // No context before the app is initialized (GlobalPreferences)
        if (!mIsChannelRow || getSection() == null || GlobalPreferences.context() == null) {
            return SectionFilterData.MODE_SHOW;
        }

        TopChannelsData data = TopChannelsData.instance(GlobalPreferences.context());

        return data.isSectionEnabled(getSection().getId()) ? data.getMode() : SectionFilterData.MODE_SHOW;
    }

    /**
     * A topic of a row of topics, hidden with its row. Also marks the topic when the setting marks instead of hiding.
     */
    private boolean isHiddenExploreTopic(Video video) {
        int mode = getExploreTopicsMode();

        if (mode == SectionFilterData.MODE_MARK) {
            video.isExploreTopicMarked = true;
        }

        return mode == SectionFilterData.MODE_HIDE;
    }

    /**
     * The mode of the Explore more topics setting for the row. Shown unless it's a row of topics of a section picked in the setting.
     */
    private int getExploreTopicsMode() {
        // No context before the app is initialized (GlobalPreferences)
        if (!mIsSearchTopicRow || getSection() == null || GlobalPreferences.context() == null) {
            return SectionFilterData.MODE_SHOW;
        }

        ExploreTopicsData data = ExploreTopicsData.instance(GlobalPreferences.context());

        return data.isSectionEnabled(getSection().getId()) ? data.getMode() : SectionFilterData.MODE_SHOW;
    }

    /**
     * The title has a keyword of the Hide content setting. Not in the lists the user made (e.g. history).
     */
    public boolean hasHiddenKeyword(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (video.isChapter || video.videoId == null || GlobalPreferences.context() == null) {
            return false;
        }

        KeywordFilterData data = KeywordFilterData.instance(GlobalPreferences.context());

        if (data.isEmpty() || !KeywordFilter.isSupportedSection(getAiSListSection())) {
            return false;
        }

        // DeArrow might have replaced the title already
        return data.isHidden(video.title) || data.isHidden(video.deArrowTitle);
    }

    public int getAiSListSection() {
        return getAiSListSection(getType(), getSection(), getMediaGroup() != null ? getMediaGroup().getChannelId() : null);
    }

    /**
     * The section AiSListManager knows a group by. The feed of a subscription group has no type: in its own section it's one of
     * its own, as a row added to Home (see HomeRowsData) it's Home's.
     * @param section the sidebar section of the group or null (e.g. search, a channel)
     */
    public static int getAiSListSection(int groupType, BrowseSection section, String groupChannelId) {
        if (section != null && section.isChannelGroup()) {
            return AiSListFilterData.SECTION_CHANNEL_GROUPS;
        }

        if (groupType == MediaGroup.TYPE_UNDEFINED && section != null && section.getId() == MediaGroup.TYPE_HOME) {
            return AiSListFilterData.SECTION_HOME;
        }

        return AiSListManager.getSection(groupType, section != null, groupChannelId);
    }

    /**
     * The section id the Collaborations, Watch later and Shows settings know the group by (see getFilterSectionId(BrowseSection, int))
     */
    public int getFilterSectionId() {
        return getFilterSectionId(getSection(), getAiSListSection());
    }

    /**
     * The section id the Collaborations, Watch later and Shows settings know a group by (see SectionFilterData):
     * its sidebar section (SectionFilterData.SECTION_CHANNEL_GROUPS for the one of a subscription group), MediaGroup.TYPE_SEARCH
     * in search or MediaGroup.TYPE_CHANNEL on a channel page, otherwise -1 (e.g. a playlist page or the player's suggestions)
     * @param aiSListSection the section AiSListManager finds for the group, only needed without a sidebar section
     */
    public static int getFilterSectionId(BrowseSection section, int aiSListSection) {
        if (section != null) {
            return section.isChannelGroup() ? SectionFilterData.SECTION_CHANNEL_GROUPS : section.getId();
        }

        if (aiSListSection == AiSListFilterData.SECTION_SEARCH) {
            return MediaGroup.TYPE_SEARCH;
        }

        return aiSListSection == AiSListManager.SECTION_CHANNEL_PAGE ? MediaGroup.TYPE_CHANNEL : -1;
    }

    /**
     * The cached u-tubot verdict, asked for before the group is created (see HiddenVideoResolver). Also marks the video.
     */
    private boolean isHiddenByUtubot(Video video) {
        // No context before the app is initialized (GlobalPreferences)
        if (!UtubotSettings.isBuiltIn() || video.isChapter || video.videoId == null || GlobalPreferences.context() == null) {
            return false;
        }

        return UtubotManager.instance(GlobalPreferences.context()).apply(video, getAiSListSection());
    }

    /**
     * Last of the filters: a video another one hides isn't counted as shown, so a row below may show it
     */
    private boolean isDuplicate(Video video) {
        if (mDuplicateFilter == null || !mDuplicateFilter.isDuplicate(video)) {
            return false;
        }

        mDuplicateCount++;

        return true;
    }

    private boolean isWatchedSuggestion(Video video) {
        if (video == null) {
            return false;
        }

        int type = getType();

        if (type != MediaGroup.TYPE_HOME && type != MediaGroup.TYPE_SUGGESTIONS) {
            return false;
        }

        if (type == MediaGroup.TYPE_HOME && getPosition() > 0) {
            return false;
        }

        return video.percentWatched > 95 || video.percentWatched == Video.MIN_WATCHED_PERCENT;
    }
}
