package com.liskovsoft.smartyoutubetv2.common.app.presenters.service;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotProcessedSection;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class SidebarServiceTest {
    @Before
    public void setUp() {
        resetSidebar();
    }

    @After
    public void tearDown() {
        Utils.sHandler.removeCallbacksAndMessages(null);
        SidebarService.resetInstanceForTesting();
        AppPrefs.instance(RuntimeEnvironment.getApplication()).setSidebarData("");
    }

    /**
     * A new sidebar starts with Home: Notifications is after Watch later
     */
    @Test
    public void newSidebarHasNotificationsAfterWatchLater() {
        List<Integer> ids = getSectionIds();

        assertEquals(MediaGroup.TYPE_HOME, (int) ids.get(0));
        assertEquals(ids.indexOf(MediaGroup.TYPE_WATCH_LATER) + 1, ids.indexOf(MediaGroup.TYPE_NOTIFICATIONS));
    }

    /**
     * Put in order without Settings (see MainUISettingsPresenter.showSidebarOrder): the others keep theirs after them, Settings
     * last, and it's kept
     */
    @Test
    public void orderedItemsFirstOthersAfterThemSettingsLast() {
        List<Integer> before = getSectionIds();

        getService().setPinnedItemsOrder(Arrays.asList(section(MediaGroup.TYPE_SUBSCRIPTIONS), section(MediaGroup.TYPE_HISTORY)));

        List<Integer> expected = new ArrayList<>();
        expected.add(MediaGroup.TYPE_SUBSCRIPTIONS);
        expected.add(MediaGroup.TYPE_HISTORY);
        for (int id : before) {
            if (!expected.contains(id)) {
                expected.add(id);
            }
        }

        assertEquals(expected, getSectionIds());
        assertEquals(MediaGroup.TYPE_SETTINGS, (int) expected.get(expected.size() - 1));

        getService().onProfileChanged(); // read again

        assertEquals(expected, getSectionIds());
    }

    /**
     * Put in order with Settings first, and with a section that isn't in the sidebar (disabled while the order was open):
     * Settings stays last, the other isn't added
     */
    @Test
    public void settingsStaysLastAndMissingSectionNotAdded() {
        List<Integer> before = getSectionIds();

        getService().setPinnedItemsOrder(Arrays.asList(section(MediaGroup.TYPE_SETTINGS), section(MediaGroup.TYPE_PLAYBACK_QUEUE)));

        assertEquals(before, getSectionIds());
    }

    /**
     * First section isn't a section, but it's kept like one (not Home, as for a section that isn't there anymore)
     */
    @Test
    public void firstSectionBootKept() {
        getService().setBootSectionId(SidebarService.BOOT_SECTION_FIRST);
        getService().onProfileChanged(); // read again

        assertEquals(SidebarService.BOOT_SECTION_FIRST, getService().getBootSectionId());
    }

    /**
     * A sidebar saved before the section existed gains Processed once; the defaults it knew stay as the user left them, so a
     * hidden or turned-off one isn't added back
     */
    @Test
    public void anOldSavedSidebarGainsTheProcessedSection() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());

        saveSidebar(Arrays.asList(section(MediaGroup.TYPE_HOME), section(MediaGroup.TYPE_SUBSCRIPTIONS)), false);
        getService().onProfileChanged();

        List<Integer> ids = getSectionIds();
        assertTrue(ids.contains(UtubotProcessedSection.ID));
        assertFalse(ids.contains(MediaGroup.TYPE_HISTORY));
        assertFalse(ids.contains(MediaGroup.TYPE_PLAYBACK_QUEUE));

        getService().onProfileChanged(); // read again, the known ids are saved now

        assertEquals(1, Collections.frequency(getSectionIds(), UtubotProcessedSection.ID));
        assertFalse(getSectionIds().contains(MediaGroup.TYPE_HISTORY));
    }

    /**
     * A sidebar saved with Processed turned off keeps it off (the known ids include it, so the migration leaves it)
     */
    @Test
    public void aSavedSidebarWithProcessedDisabledKeepsItDisabled() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());

        assertTrue(getSectionIds().contains(UtubotProcessedSection.ID));
        getService().enableSection(UtubotProcessedSection.ID, false);
        getService().onProfileChanged(); // read again

        assertFalse(getSectionIds().contains(UtubotProcessedSection.ID));
    }

    /**
     * Written as the versions before the known-id part did: pinned items, boot section, Settings enabled
     */
    private static void saveSidebar(List<Video> items, boolean settingsEnabled) {
        AppPrefs.instance(RuntimeEnvironment.getApplication()).setSidebarData(
                Helpers.mergeData(Helpers.mergeList(items), MediaGroup.TYPE_HOME, settingsEnabled));
    }

    private static Video section(int sectionId) {
        Video item = new Video();
        item.sectionId = sectionId;
        return item;
    }

    /**
     * A subscription group is known by its id, whatever its title (it can be renamed): out of the sidebar once unpinned
     */
    @Test
    public void groupIsPinnedByItsId() {
        getService().addPinnedItem(group("group1", "Climbing"));

        assertTrue(getService().isPinned(group("group1", "Bouldering")));
        assertFalse(getService().isPinned(group("group2", "Climbing")));

        getService().removePinnedItem(group("group1", "Climbing"));

        assertFalse(getService().isPinned(group("group1", "Climbing")));
    }

    /**
     * A pinned group by an id the group had before takes its id now (see ChannelGroupServiceWrapper.normalizeReferences), the boot
     * section with it; two of one group become one; saved
     */
    @Test
    public void pinnedGroupTakesTheGroupsIdNow() {
        getService().addPinnedItem(group("Ab12Cd34Ef56", "Music"));
        getService().addPinnedItem(group("Gh78Ij90Kl12", "Music"));
        getService().addPinnedItem(group("t-1111111111111111", "Climbing"));
        getService().setBootSectionId(group("Ab12Cd34Ef56", "Music").getId());

        int oldSectionId = group("Ab12Cd34Ef56", "Music").getId();
        Map<String, String> ids = new HashMap<>();
        ids.put("Ab12Cd34Ef56", "t-2222222222222222");
        ids.put("Gh78Ij90Kl12", "t-2222222222222222");
        Map<Integer, Integer> sectionIds = getService().normalizeGroupIds(ids::get, id -> null);

        assertEquals(group("t-2222222222222222", "Music").getId(), (int) sectionIds.get(oldSectionId));

        for (int i = 0; i < 2; i++) {
            assertEquals(Arrays.asList("t-1111111111111111", "t-2222222222222222"), getGroupIds());
            assertFalse(getService().isPinned(group("Ab12Cd34Ef56", "Music")));
            assertEquals(group("t-2222222222222222", "Music").getId(), getService().getBootSectionId());

            getService().onProfileChanged(); // read again
        }
    }

    /**
     * Sorted: where a group goes depends on its hash (see SidebarService.addPinnedItem)
     */
    /**
     * A pinned playlist kept on the device by its old random id takes the playlist's id now, as its playlist id and its channel id
     * (see BrowseService2Wrapper.getCachedPlaylists); a YouTube playlist keeps its own
     */
    @Test
    public void pinnedPlaylistTakesThePlaylistsIdNow() {
        getService().addPinnedItem(playlist("Ab12Cd34Ef56", "Climbing"));
        getService().addPinnedItem(playlist("PLyoutubeplaylist", "Music"));
        int oldSectionId = playlist("Ab12Cd34Ef56", "Climbing").getId();

        Map<String, String> ids = new HashMap<>();
        ids.put("Ab12Cd34Ef56", "p-3333333333333333");
        ids.put("PLyoutubeplaylist", "PLyoutubeplaylist");
        Map<Integer, Integer> sectionIds = getService().normalizeGroupIds(id -> null, ids::get);

        assertEquals(Collections.singletonMap(oldSectionId, playlist("p-3333333333333333", "Climbing").getId()), sectionIds);
        assertTrue(getService().isPinned(playlist("p-3333333333333333", "Climbing")));
        assertTrue(getService().isPinned(playlist("PLyoutubeplaylist", "Music")));
        assertFalse(getService().isPinned(playlist("Ab12Cd34Ef56", "Climbing")));

        for (Video item : getService().getPinnedItems()) {
            if ("p-3333333333333333".equals(item.playlistId)) {
                assertEquals("p-3333333333333333", item.channelId);
            }
        }
    }

    private static Video playlist(String playlistId, String title) {
        Video item = new Video();
        item.playlistId = playlistId;
        item.channelId = playlistId;
        item.title = title;
        return item;
    }

    private static List<String> getGroupIds() {
        List<String> result = new ArrayList<>();

        for (Video item : getService().getPinnedItems()) {
            if (item.channelGroupId != null) {
                result.add(item.channelGroupId);
            }
        }

        Collections.sort(result);
        return result;
    }

    private static Video group(String channelGroupId, String title) {
        Video item = new Video();
        item.channelGroupId = channelGroupId;
        item.title = title;
        return item;
    }

    private static List<Integer> getSectionIds() {
        List<Integer> result = new ArrayList<>();

        for (Video item : getService().getPinnedItems()) {
            result.add(item.sectionId);
        }

        return result;
    }

    /**
     * A new sidebar (see SidebarService.initPinnedItems)
     */
    private static void resetSidebar() {
        AppPrefs.instance(RuntimeEnvironment.getApplication()).setSidebarData(""); // not null: it isn't written, the old data stays
        getService().onProfileChanged();
    }

    private static SidebarService getService() {
        return SidebarService.instance(RuntimeEnvironment.getApplication());
    }
}
