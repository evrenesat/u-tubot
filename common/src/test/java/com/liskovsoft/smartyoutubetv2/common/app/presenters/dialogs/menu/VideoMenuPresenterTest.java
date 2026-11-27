package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class VideoMenuPresenterTest {
    /**
     * A Video holds its group weakly: without a strong reference here a GC between the setup and the assert drops the group
     */
    private static final List<VideoGroup> sGroups = new ArrayList<>();

    /**
     * The row of Subscriptions added to Home is the same group as the section (see BrowsePresenter.createAddedHomeRowObserve)
     */
    @Test
    public void subscriptionsAndNotificationsHaveTheSubscriptionsMenu() {
        assertEquals(MainUIData.MENU_SUBSCRIPTIONS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_SUBSCRIPTIONS), false, false));
        assertEquals(MainUIData.MENU_SUBSCRIPTIONS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_NOTIFICATIONS), false, false));
    }

    @Test
    public void historyHasTheHistoryMenu() {
        assertEquals(MainUIData.MENU_HISTORY, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_HISTORY), false, false));
        assertEquals(MainUIData.MENU_HISTORY, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_HOME), true, false));
    }

    @Test
    public void playlistsSectionHasThePlaylistsMenu() {
        assertEquals(MainUIData.MENU_PLAYLISTS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_USER_PLAYLISTS), false, true));
    }

    /**
     * Home, Search, the channels, the player...
     */
    @Test
    public void otherPlacesHaveTheVideosMenu() {
        assertEquals(MainUIData.MENU_VIDEOS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_HOME), false, false));
        assertEquals(MainUIData.MENU_VIDEOS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_SEARCH), false, false));
        assertEquals(MainUIData.MENU_VIDEOS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_SUGGESTIONS), false, false));
        assertEquals(MainUIData.MENU_VIDEOS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_USER_PLAYLISTS), false, false));
        assertEquals(MainUIData.MENU_VIDEOS, VideoMenuPresenter.getCardMenu(new Video(), false, false));
    }

    /**
     * Where it is wins over the section shown
     */
    @Test
    public void subscriptionsWinOverTheSectionShown() {
        assertEquals(MainUIData.MENU_SUBSCRIPTIONS, VideoMenuPresenter.getCardMenu(createVideo(MediaGroup.TYPE_SUBSCRIPTIONS), true, true));
    }

    private static Video createVideo(int type) {
        VideoGroup group = VideoGroup.from(new ArrayList<>());
        group.setType(type);
        Video video = new Video();
        video.videoId = "video";
        sGroups.add(group);
        video.setGroup(group);
        return video;
    }
}
