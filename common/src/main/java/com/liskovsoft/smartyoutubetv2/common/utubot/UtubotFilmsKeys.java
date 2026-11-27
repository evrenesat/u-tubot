package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.view.KeyEvent;

/**
 * What the film screen does with Back, so it behaves like the YouTube player: with the stream list (or any overlay) up, Back closes it and
 * playback goes on; the next Back leaves the screen. Never the app.
 */
public final class UtubotFilmsKeys {
    public enum Result {
        /** Not Back: the screen handles the key as usual */
        NONE,
        /** Close the overlay, playback goes on */
        HIDE_OVERLAY,
        /** Leave the screen (back to where it was opened from) */
        LEAVE,
        /** The release of a Back whose press was handled */
        CONSUME
    }

    private UtubotFilmsKeys() {
    }

    /**
     * @param isOverlayVisible the stream list or another overlay is on screen while a stream plays
     * @param isPlaying a stream has been started (before that the list is the screen, and Back leaves it)
     */
    public static Result resolveBack(int keyCode, int action, int repeatCount, boolean isOverlayVisible, boolean isPlaying) {
        if (!UtubotKeys.isBackKey(keyCode)) {
            return Result.NONE;
        }

        if (action != KeyEvent.ACTION_DOWN || repeatCount != 0) {
            return Result.CONSUME;
        }

        return isOverlayVisible && isPlaying ? Result.HIDE_OVERLAY : Result.LEAVE;
    }
}
