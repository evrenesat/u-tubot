package com.liskovsoft.smartyoutubetv2.common.app.presenters.service;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs.ProfileChangeListener;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotProcessedSection;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

public class SidebarService implements ProfileChangeListener {
    @SuppressLint("StaticFieldLeak")
    private static SidebarService sInstance;
    private final Context mContext;
    private List<Video> mPinnedItems;
    private final Map<Integer, Integer> mDefaultSections = new LinkedHashMap<>();
    private final AppPrefs mPrefs;
    private boolean mIsSettingsSectionEnabled;
    private int mBootSectionId;
    private final static int RESERVED_ID = 100;
    /**
     * Boot to the section at the top of the sidebar, whichever it is. Below RESERVED_ID, so no pinned item has it (see
     * cleanupPinnedItems), and past the ids of the sections (MediaGroup.TYPE_...).
     */
    public final static int BOOT_SECTION_FIRST = RESERVED_ID - 1;

    private SidebarService(Context context) {
        mContext = context.getApplicationContext();
        mPrefs = AppPrefs.instance(context);
        mPrefs.addListener(this);
        initSections();
        restoreState();
    }

    public static SidebarService instance(Context context) {
        if (sInstance == null && context != null) {
            sInstance = new SidebarService(context.getApplicationContext());
        }

        return sInstance;
    }

    /**
     * The one made, without making it: null while nothing has read the sidebar
     */
    @Nullable
    public static SidebarService peekInstance() {
        return sInstance;
    }

    public Collection<Video> getPinnedItems() {
        return Collections.unmodifiableList(mPinnedItems);
    }

    public int addPinnedItem(Video item) {
        if (mPinnedItems.contains(item)) {
            return -1;
        }

        int idx = Helpers.indexOfFirst(mPinnedItems, obj -> obj.getId() > RESERVED_ID);

        if (idx != -1) {
            mPinnedItems.add(idx, item);
        } else {
            mPinnedItems.add(item);
        }
        persistState();

        // Not idx: appended, it's moved before Settings (see keepSettingsLast)
        return mPinnedItems.indexOf(item);
    }

    public void removePinnedItem(Video item) {
        mPinnedItems.remove(item);
        persistState();
    }

    public void enableSection(int sectionId, boolean enabled) {
        if (enabled) {
            if (sectionId == MediaGroup.TYPE_SETTINGS) {
                mIsSettingsSectionEnabled = true; // prevent Settings lock
            }

            //Video item = new Video();
            //item.sectionId = sectionId;
            //
            //if (mPinnedItems.contains(item)) { // don't reorder if item already exists
            //    return;
            //}

            Video section = Helpers.findFirst(mPinnedItems, item -> item != null && item.sectionId == sectionId);

            if (section != null) { // don't reorder if item already exists
                return;
            }

            Video item = new Video();
            item.sectionId = sectionId;

            mPinnedItems.add(getInsertIndex(sectionId), item);
        } else {
            Helpers.removeIf(mPinnedItems, item -> item == null || item.sectionId == sectionId);
        }

        persistState();
    }

    public Map<Integer, Integer> getDefaultSections() {
        return mDefaultSections;
    }

    /**
     * Right after the closest section before it in the default order (see initSections) that's in the sidebar, at the top
     * when there's none. Not its index in the default order: the sidebar may lack sections before it (e.g. Notifications)
     * or be reordered.
     */
    private int getInsertIndex(int sectionId) {
        int index = 0;

        for (int defaultId : mDefaultSections.values()) {
            if (defaultId == sectionId) {
                break;
            }

            int found = Helpers.indexOfFirst(mPinnedItems, item -> item != null && item.sectionId == defaultId);

            if (found != -1) {
                index = found + 1;
            }
        }

        return index;
    }

    private int getDefaultSectionIndex(int sectionId) {
        int index = -1;

        Collection<Integer> values = mDefaultSections.values();

        for (int item : values) {
            index++;
            if (item == sectionId) {
                break;
            }
        }

        return index;
    }

    /**
     * The pinned item is in the sidebar (e.g. a subscription group, see Video.from(ItemGroup))
     */
    public boolean isPinned(Video item) {
        return mPinnedItems.contains(item);
    }

    /**
     * Contains sections and pinned items!
     */
    public boolean isSectionPinned(int sectionId) {
        Video section = Helpers.findFirst(mPinnedItems, item -> getSectionId(item) == sectionId);
        return section != null; // by default enable all pinned items
    }

    public int getSectionIndex(int sectionId) {
        // 1) Distinguish section from pinned item
        // 2) Add pinned items after the sections

        int index = findPinnedItemIndex(sectionId);

        return index;
    }

    public void renameSection(int sectionId, String newTitle) {
        int index = findPinnedItemIndex(sectionId);
        if (index != -1) {
            Video video = mPinnedItems.get(index);
            video.title = newTitle;
            persistState();
        }
    }

    /**
     * The ones not in it (e.g. Settings) come after them, Settings last (see keepSettingsLast)
     */
    public void setPinnedItemsOrder(List<Video> items) {
        List<Video> result = new ArrayList<>();

        for (Video item : items) {
            // Not there anymore (e.g. disabled since or another profile's)
            if (mPinnedItems.contains(item) && !result.contains(item)) {
                result.add(item);
            }
        }

        for (Video item : mPinnedItems) {
            if (!result.contains(item)) {
                result.add(item);
            }
        }

        mPinnedItems = result;
        persistState();
    }

    public void moveSectionUp(int sectionId) {
        shiftSection(sectionId, -1);
    }

    public void moveSectionDown(int sectionId) {
        shiftSection(sectionId, 1);
    }

    public boolean canMoveSectionUp(int sectionId) {
        return canShiftSection(sectionId, -1);
    }

    public boolean canMoveSectionDown(int sectionId) {
        return canShiftSection(sectionId, 1);
    }

    /**
     * The sections in the default order (see initSections), then the pinned items as they were, and Settings last
     */
    public void sortSectionsByDefault() {
        // Stable: the pinned items keep their order
        Collections.sort(mPinnedItems, (o1, o2) -> Integer.compare(getDefaultOrder(o1), getDefaultOrder(o2)));
        persistState();
    }

    private int getDefaultOrder(Video item) {
        return item == null || item.sectionId == -1 ? Integer.MAX_VALUE : getDefaultSectionIndex(item.sectionId);
    }

    private boolean canShiftSection(int sectionId, int shift) {
        int index = findPinnedItemIndex(sectionId);

        if (index != -1) {
            return  index + shift >= 0 && index + shift < mPinnedItems.size();
        }

        return false;
    }

    private void shiftSection(int sectionId, int shift) {
        if (!canShiftSection(sectionId, shift)) {
            return;
        }

        int index = findPinnedItemIndex(sectionId);

        if (index != -1) {
            Video current = mPinnedItems.get(index);
            mPinnedItems.remove(current);

            mPinnedItems.add(index + shift, current);
            persistState();
        }
    }

    private int findPinnedItemIndex(int sectionId) {
        int index = -1;

        for (Video item : mPinnedItems) {
            // Distinguish pinned items by hashCode or extra field (default section)!
            if (getSectionId(item) == sectionId) {
                index = mPinnedItems.indexOf(item);
                break;
            }
        }

        return index;
    }

    public void setBootSectionId(int sectionId) {
        mBootSectionId = sectionId;

        persistState();
    }

    public int getBootSectionId() {
        return mBootSectionId;
    }

    public void enableSettingsSection(boolean enabled) {
        mIsSettingsSectionEnabled = enabled;

        persistState();
    }

    public boolean isSettingsSectionEnabled() {
        return mIsSettingsSectionEnabled;
    }

    private int getSectionId(Video item) {
        if (item == null) {
            return -1;
        }

        return item.sectionId == -1 ? item.getId() : item.sectionId;
    }

    private void initSections() {
        mDefaultSections.put(R.string.header_home, MediaGroup.TYPE_HOME);
        mDefaultSections.put(R.string.header_shorts, MediaGroup.TYPE_SHORTS);
        mDefaultSections.put(R.string.header_kids_home, MediaGroup.TYPE_KIDS_HOME);
        mDefaultSections.put(R.string.header_sports, MediaGroup.TYPE_SPORTS);
        mDefaultSections.put(R.string.badge_live, MediaGroup.TYPE_LIVE);
        mDefaultSections.put(R.string.header_gaming, MediaGroup.TYPE_GAMING);
        mDefaultSections.put(R.string.header_news, MediaGroup.TYPE_NEWS);
        mDefaultSections.put(R.string.header_music, MediaGroup.TYPE_MUSIC);
        mDefaultSections.put(R.string.header_channels, MediaGroup.TYPE_CHANNEL_UPLOADS);
        mDefaultSections.put(R.string.header_subscriptions, MediaGroup.TYPE_SUBSCRIPTIONS);
        mDefaultSections.put(R.string.header_history, MediaGroup.TYPE_HISTORY);
        mDefaultSections.put(R.string.watch_later, MediaGroup.TYPE_WATCH_LATER);
        mDefaultSections.put(R.string.header_notifications, MediaGroup.TYPE_NOTIFICATIONS);
        mDefaultSections.put(R.string.header_blocked_channels, MediaGroup.TYPE_BLOCKED_CHANNELS);
        mDefaultSections.put(R.string.header_blocked_ai_channels, MediaGroup.TYPE_BLOCKED_AI_CHANNELS);
        mDefaultSections.put(R.string.unhide, MediaGroup.TYPE_HIDDEN_VIDEOS);
        mDefaultSections.put(R.string.header_playlists, MediaGroup.TYPE_USER_PLAYLISTS);
        mDefaultSections.put(R.string.my_videos, MediaGroup.TYPE_MY_VIDEOS);
        mDefaultSections.put(R.string.playback_queue_category_title, MediaGroup.TYPE_PLAYBACK_QUEUE);

        // Past the other entries: the built-in flavor only (u-tubot #66), next to Settings, which it keeps last
        if (UtubotSettings.isBuiltIn()) {
            mDefaultSections.put(R.string.utubot_processed_title, UtubotProcessedSection.ID);
        }

        mDefaultSections.put(R.string.header_settings, MediaGroup.TYPE_SETTINGS);
    }

    private void initPinnedItems() {
        for (int sectionId : mDefaultSections.values()) {
            // Hidden sections
            enableSection(sectionId, !Helpers.equalsAny(sectionId, new int[] {
                    MediaGroup.TYPE_PLAYBACK_QUEUE,
                    MediaGroup.TYPE_BLOCKED_CHANNELS,
                    MediaGroup.TYPE_BLOCKED_AI_CHANNELS,
                    MediaGroup.TYPE_HIDDEN_VIDEOS
            }));
        }
    }

    private void cleanupPinnedItems() {
        Helpers.removeDuplicates(mPinnedItems);

        Helpers.removeIf(mPinnedItems, item -> {
            if (item == null) {
                return true;
            }

            item.videoId = null;

            // Fix id collision between pinned and default sections
            if (item.getId() < RESERVED_ID && item.getId() >= -1 && item.sectionId == -1) {
                return true;
            }

            // A section that isn't there anymore (e.g. Trending)
            if (item.sectionId != -1 && !mDefaultSections.containsValue(item.sectionId)) {
                return true;
            }

            return !item.hasPlaylist() && item.channelId == null && item.sectionId == -1 && item.channelGroupId == null && !item.hasReloadPageKey();
        });
    }

    private void restoreState() {
        String data = mPrefs.getSidebarData();

        String[] split = Helpers.splitData(data);

        mPinnedItems = Helpers.parseList(split, 0, Video::fromString);
        mBootSectionId = Helpers.parseInt(split, 1, MediaGroup.TYPE_HOME);

        // A section that isn't there anymore (e.g. Trending). Pinned items have ids past RESERVED_ID (see cleanupPinnedItems).
        if (mBootSectionId >= 0 && mBootSectionId < RESERVED_ID && mBootSectionId != BOOT_SECTION_FIRST
                && !mDefaultSections.containsValue(mBootSectionId)) {
            mBootSectionId = MediaGroup.TYPE_HOME;
        }

        mIsSettingsSectionEnabled = Helpers.parseBoolean(split, 2, true);

        transferOldPinnedItems();

        if (mPinnedItems.isEmpty()) {
            initPinnedItems();
        }

        // Backward compatibility
        enableSection(MediaGroup.TYPE_SETTINGS, true);

        cleanupPinnedItems();

        keepSettingsLast();
    }

    private void transferOldPinnedItems() {
        if (mPinnedItems != null && !mPinnedItems.isEmpty()) {
            return;
        }

        List<Video> oldPinnedItems = GeneralData.instance(mContext).getOldPinnedItems();

        if (oldPinnedItems != null && !oldPinnedItems.isEmpty()) {
            mPinnedItems = oldPinnedItems;
        }
    }

    /**
     * Settings is always the last section: the sections and pinned items are added at the end, e.g. all of them again when
     * Child mode is turned off, and a sidebar saved before kept it first.
     */
    private void keepSettingsLast() {
        int index = findPinnedItemIndex(MediaGroup.TYPE_SETTINGS);

        if (index != -1 && index != mPinnedItems.size() - 1) {
            mPinnedItems.add(mPinnedItems.remove(index));
        }
    }

    public void persistState() {
        keepSettingsLast();
        mPrefs.setSidebarData(Helpers.mergeData(mPinnedItems, mBootSectionId, mIsSettingsSectionEnabled));
    }

    /**
     * The pinned subscription groups and playlists kept on the device refer to them by the ids they have now (see
     * GroupReferences). A section is known by the item's hash, which has the id: the boot section follows it. Saved when an item
     * changed.
     * @return the sections whose id changed: the old id to the new one
     */
    public Map<Integer, Integer> normalizeGroupIds(Function<String, String> channelGroupId, Function<String, String> playlistId) {
        Map<Integer, Integer> sectionIds = new HashMap<>();
        boolean isChanged = false;
        List<Video> result = new ArrayList<>();

        for (Video item : mPinnedItems) {
            if (item != null) {
                int oldSectionId = getSectionId(item);

                if (item.normalizeGroupIds(channelGroupId, playlistId)) {
                    int sectionId = getSectionId(item); // the hash again, saved with the item
                    isChanged = true;

                    if (sectionId != oldSectionId) {
                        sectionIds.put(oldSectionId, sectionId);

                        if (mBootSectionId == oldSectionId) {
                            mBootSectionId = sectionId;
                        }
                    }
                }
            }

            // Two of one group, made by two devices before
            if (result.contains(item)) {
                isChanged = true;
            } else {
                result.add(item);
            }
        }

        if (isChanged) {
            mPinnedItems = result;
            persistState();
        }

        return sectionIds;
    }

    @Override
    public void onProfileChanged() {
        restoreState();
    }

    @Override
    public void onProfileDataSynced(Set<String> keys) {
        if (keys.contains(AppPrefs.SIDEBAR_DATA)) {
            restoreState();
        }
    }

    /**
     * The next instance reads the saved values again. This one isn't told of the profile changes anymore: it would write its
     * sidebar into another test's profiles (see restoreState).
     */
    static void resetInstanceForTesting() {
        if (sInstance != null) {
            sInstance.mPrefs.removeListener(sInstance);
            sInstance = null;
        }
    }
}
