package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.view.KeyEvent;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;

import java.util.Collections;
import java.util.List;

/**
 * Moving between the Inbox results from an opened one (u-tubot #223): next and previous open the neighbouring tile in the Inbox's order,
 * newest first, and stop at the ends. The landed result is marked read.
 */
public final class UtubotInboxNavigation {
    /** Toward the older results, the order of the list */
    public static final int NEXT = 1;
    /** Toward the newer results */
    public static final int PREVIOUS = -1;
    /** No move */
    public static final int NONE = 0;

    private UtubotInboxNavigation() {
    }

    /**
     * The step a key asks for: media next or channel down is NEXT, media previous or channel up is PREVIOUS, else NONE
     */
    public static int stepOf(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_MEDIA_NEXT:
            case KeyEvent.KEYCODE_CHANNEL_DOWN:
                return NEXT;
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
            case KeyEvent.KEYCODE_CHANNEL_UP:
                return PREVIOUS;
            default:
                return NONE;
        }
    }

    /**
     * Whether the tile is an Inbox result (see UtubotInboxSection.toVideo)
     */
    public static boolean isInboxTile(@Nullable Video tile) {
        return tile != null && tile.inboxKind != null;
    }

    /**
     * The tile one step away from the current one in the Inbox's list order. Null at the ends (the move stops there), when the step is
     * NONE, when the current tile is not an Inbox result or is not in the list.
     */
    @Nullable
    public static Video neighbour(@Nullable List<Video> tiles, @Nullable Video current, int step) {
        if (tiles == null || !isInboxTile(current) || step == NONE) {
            return null;
        }

        int index = indexOf(tiles, current);

        if (index < 0) {
            return null;
        }

        int target = index + step;

        return target >= 0 && target < tiles.size() ? tiles.get(target) : null;
    }

    /**
     * The Inbox ids to mark read when the tile is landed on: its own id, none for a tile that is not an Inbox result
     */
    public static List<Long> idsToMarkRead(@Nullable Video landed) {
        return isInboxTile(landed) && landed.inboxId > 0 ? Collections.singletonList(landed.inboxId) : Collections.<Long>emptyList();
    }

    private static int indexOf(List<Video> tiles, Video current) {
        for (int i = 0; i < tiles.size(); i++) {
            Video tile = tiles.get(i);

            if (tile != null && tile.inboxId == current.inboxId && current.videoId != null && current.videoId.equals(tile.videoId)) {
                return i;
            }
        }

        return -1;
    }
}
