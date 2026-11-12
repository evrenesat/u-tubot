package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.view.KeyEvent;

import org.junit.Test;

import static com.liskovsoft.smartyoutubetv2.common.utubot.UtubotKeys.Result;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotKeysTest {
    private static Result resolve(int key, int action, int repeat, boolean viewOpen, boolean panelMode, boolean cardFocused) {
        return UtubotKeys.resolve(key, action, repeat, viewOpen, panelMode, cardFocused, false);
    }

    private static Result resolveWithPanel(int key, int action, int repeat, boolean viewOpen) {
        return UtubotKeys.resolve(key, action, repeat, viewOpen, true, true, true);
    }

    @Test
    public void infoOnACardOpensTheSummaryViewWhileThePanelModeIsOn() {
        assertEquals(Result.OPEN_SUMMARY, resolve(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_DOWN, 0, false, true, true));
    }

    @Test
    public void infoKeepsItsMenuBindingWithoutAPanelModeOrACard() {
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_DOWN, 0, false, false, true));
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_DOWN, 0, false, true, false));
    }

    @Test
    public void menuKeysAreLeftToTheVideoMenu() {
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_MENU, KeyEvent.ACTION_DOWN, 0, false, true, true));
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.ACTION_DOWN, 0, false, true, true));
    }

    @Test
    public void aHeldOrReleasedInfoKeyOpensNothingTwice() {
        assertEquals(Result.CONSUME, resolve(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_DOWN, 1, false, true, true));
        assertEquals(Result.CONSUME, resolve(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_UP, 0, false, true, true));
    }

    @Test
    public void backClosesTheOpenViewOnce() {
        assertEquals(Result.CLOSE_VIEW, resolve(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 0, true, true, false));
        assertEquals(Result.CLOSE_VIEW, resolve(KeyEvent.KEYCODE_ESCAPE, KeyEvent.ACTION_DOWN, 0, true, true, false));
        assertEquals(Result.CONSUME, resolve(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 1, true, true, false));
        assertEquals(Result.CONSUME, resolve(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_UP, 0, true, true, false));
    }

    @Test
    public void backGoesOnWhenNoViewIsOpen() {
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 0, false, true, true));
    }

    @Test
    public void backHidesTheVisiblePanelFirst() {
        assertEquals(Result.HIDE_PANEL, resolveWithPanel(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 0, false));
        assertEquals(Result.HIDE_PANEL, resolveWithPanel(KeyEvent.KEYCODE_ESCAPE, KeyEvent.ACTION_DOWN, 0, false));
    }

    @Test
    public void aHeldOrReleasedBackIsLeftToTheCaller() {
        assertEquals(Result.NONE, resolveWithPanel(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 1, false));
        assertEquals(Result.NONE, resolveWithPanel(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_UP, 0, false));
    }

    @Test
    public void withoutAPanelBackIsTheAppsOwn() {
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 0, false, true, true));
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 0, false, true, false));
    }

    @Test
    public void theOpenViewComesBeforeThePanelForBack() {
        assertEquals(Result.CLOSE_VIEW, resolveWithPanel(KeyEvent.KEYCODE_BACK, KeyEvent.ACTION_DOWN, 0, true));
    }

    @Test
    public void thePanelTakesNoOtherKeyThanBack() {
        for (int key : new int[]{KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_MENU, KeyEvent.KEYCODE_HOME, KeyEvent.KEYCODE_ENTER}) {
            assertEquals(Result.NONE, resolveWithPanel(key, KeyEvent.ACTION_DOWN, 0, false));
        }

        assertEquals(Result.TOUCH, resolveWithPanel(KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.ACTION_DOWN, 0, false));
        assertEquals(Result.OPEN_SUMMARY, resolveWithPanel(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_DOWN, 0, false));
    }

    @Test
    public void theOpenViewLeavesTheOtherKeysToItsViews() {
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.ACTION_DOWN, 0, true, true, false));
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.ACTION_DOWN, 0, true, true, false));
        assertEquals(Result.NONE, resolve(KeyEvent.KEYCODE_INFO, KeyEvent.ACTION_DOWN, 0, true, true, false));
    }

    @Test
    public void directionKeysKeepThePanelWaiting() {
        for (int key : new int[]{KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT}) {
            assertEquals(Result.TOUCH, resolve(key, KeyEvent.ACTION_DOWN, 0, false, true, true));
            assertEquals(Result.TOUCH, resolve(key, KeyEvent.ACTION_DOWN, 7, false, true, true));
            assertEquals(Result.TOUCH, resolve(key, KeyEvent.ACTION_UP, 0, false, true, true));
        }
    }

    @Test
    public void keyClasses() {
        assertTrue(UtubotKeys.isSummaryKey(KeyEvent.KEYCODE_INFO));
        assertFalse(UtubotKeys.isSummaryKey(KeyEvent.KEYCODE_MENU));
        assertTrue(UtubotKeys.isBackKey(KeyEvent.KEYCODE_BACK));
        assertFalse(UtubotKeys.isDirectionKey(KeyEvent.KEYCODE_BACK));
    }
}
