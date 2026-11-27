package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.view.KeyEvent;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxKind;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * Next and previous between the Inbox results (u-tubot #223): the list order, the stop at the ends and the mark read.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotInboxNavigationTest {
    private final List<Video> mTiles = new ArrayList<>(Arrays.asList(
            tile(3, InboxKind.SUMMARY, "vid3"),
            tile(2, InboxKind.CUT, "vid2"),
            tile(1, InboxKind.RESEARCH, "vid1")));

    @Test
    public void nextIsTheFollowingTileAndPreviousTheOneBefore() {
        assertSame(mTiles.get(1), UtubotInboxNavigation.neighbour(mTiles, mTiles.get(0), UtubotInboxNavigation.NEXT));
        assertSame(mTiles.get(2), UtubotInboxNavigation.neighbour(mTiles, mTiles.get(1), UtubotInboxNavigation.NEXT));
        assertSame(mTiles.get(0), UtubotInboxNavigation.neighbour(mTiles, mTiles.get(1), UtubotInboxNavigation.PREVIOUS));
    }

    @Test
    public void theMoveStopsAtTheEnds() {
        assertNull(UtubotInboxNavigation.neighbour(mTiles, mTiles.get(2), UtubotInboxNavigation.NEXT));
        assertNull(UtubotInboxNavigation.neighbour(mTiles, mTiles.get(0), UtubotInboxNavigation.PREVIOUS));
    }

    @Test
    public void aTileOutsideTheListOrAWrongStepMovesNowhere() {
        Video outside = tile(9, InboxKind.CUT, "vid9");

        assertNull(UtubotInboxNavigation.neighbour(mTiles, outside, UtubotInboxNavigation.NEXT));
        assertNull(UtubotInboxNavigation.neighbour(mTiles, mTiles.get(1), UtubotInboxNavigation.NONE));
        assertNull(UtubotInboxNavigation.neighbour(null, mTiles.get(1), UtubotInboxNavigation.NEXT));
    }

    @Test
    public void aNormalCardHasNoInboxNeighbour() {
        Video card = new Video();
        card.videoId = "vid2";

        assertNull(UtubotInboxNavigation.neighbour(mTiles, card, UtubotInboxNavigation.NEXT));
        assertTrue(!UtubotInboxNavigation.isInboxTile(card));
    }

    @Test
    public void theKeysAreMediaAndChannelKeys() {
        assertEquals(UtubotInboxNavigation.NEXT, UtubotInboxNavigation.stepOf(KeyEvent.KEYCODE_MEDIA_NEXT));
        assertEquals(UtubotInboxNavigation.NEXT, UtubotInboxNavigation.stepOf(KeyEvent.KEYCODE_CHANNEL_DOWN));
        assertEquals(UtubotInboxNavigation.PREVIOUS, UtubotInboxNavigation.stepOf(KeyEvent.KEYCODE_MEDIA_PREVIOUS));
        assertEquals(UtubotInboxNavigation.PREVIOUS, UtubotInboxNavigation.stepOf(KeyEvent.KEYCODE_CHANNEL_UP));
        assertEquals(UtubotInboxNavigation.NONE, UtubotInboxNavigation.stepOf(KeyEvent.KEYCODE_DPAD_DOWN));
    }

    @Test
    public void theLandedResultIsMarkedReadAndOnlyAnInboxResultIs() {
        assertEquals(Collections.singletonList(2L), UtubotInboxNavigation.idsToMarkRead(mTiles.get(1)));
        assertTrue(UtubotInboxNavigation.idsToMarkRead(new Video()).isEmpty());
        assertTrue(UtubotInboxNavigation.idsToMarkRead(null).isEmpty());
    }

    private static Video tile(long id, String kind, String videoId) {
        Video video = new Video();
        video.inboxId = id;
        video.inboxKind = kind;
        video.videoId = videoId;

        return video;
    }
}
