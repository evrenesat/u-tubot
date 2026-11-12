package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.view.KeyEvent;

/**
 * What the u-tubot overlays do with a key, before the activity handles it
 */
public final class UtubotKeys {
    public enum Result {
        /** Not ours: the key goes on */
        NONE,
        /** The user is still moving: the pause before a summary starts again; the key goes on */
        TOUCH,
        /** Open the Summary view for the focused card; the key is used */
        OPEN_SUMMARY,
        /** Close the Summary view; the key is used */
        CLOSE_VIEW,
        /** Back with the passive panel up: the panel goes first, the focus stays; the key is used. The next Back is the app's. */
        HIDE_PANEL,
        /** Used, nothing to do (e.g. the release of a key whose press was ours) */
        CONSUME
    }

    private UtubotKeys() {
    }

    /**
     * The key that opens the Summary view while the passive panel is on. Electric Eel opens the video menu with it (see
     * KeyHelpers.isMenuKey): the menu stays on Menu and the long press of OK.
     */
    public static boolean isSummaryKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_INFO;
    }

    public static boolean isBackKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_ESCAPE;
    }

    public static boolean isDirectionKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_DPAD_UP || keyCode == KeyEvent.KEYCODE_DPAD_DOWN ||
                keyCode == KeyEvent.KEYCODE_DPAD_LEFT || keyCode == KeyEvent.KEYCODE_DPAD_RIGHT;
    }

    /**
     * OK on the remote, Enter on a keyboard, A on a gamepad: the keys that activate the focused view
     */
    public static boolean isSelectKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER || keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER ||
                keyCode == KeyEvent.KEYCODE_BUTTON_A;
    }

    /**
     * A key that works on the view that has the focus: it moves the focus (D-pad) or activates the view (OK, Enter)
     */
    public static boolean actsOnFocus(int keyCode) {
        return isDirectionKey(keyCode) || isSelectKey(keyCode);
    }

    /**
     * @param isViewOpen the Summary view (or the AI answer) is up
     * @param isPanelMode the passive panel mode is on (the Summary view's key works with it)
     * @param isCardFocused a card with a video has the focus
     * @param isPanelVisible the passive panel is up (waiting, loading or showing a summary)
     */
    public static Result resolve(int keyCode, int action, int repeatCount, boolean isViewOpen, boolean isPanelMode, boolean isCardFocused,
                                 boolean isPanelVisible) {
        boolean isDown = action == KeyEvent.ACTION_DOWN;

        if (isViewOpen) {
            return isBackKey(keyCode) ? (isDown && repeatCount == 0 ? Result.CLOSE_VIEW : Result.CONSUME) : Result.NONE;
        }

        if (isBackKey(keyCode) && isPanelVisible) {
            return isDown && repeatCount == 0 ? Result.HIDE_PANEL : Result.NONE;
        }

        if (isSummaryKey(keyCode) && isPanelMode && isCardFocused) {
            return isDown && repeatCount == 0 ? Result.OPEN_SUMMARY : Result.CONSUME;
        }

        if (isDirectionKey(keyCode)) {
            return Result.TOUCH;
        }

        return Result.NONE;
    }
}
