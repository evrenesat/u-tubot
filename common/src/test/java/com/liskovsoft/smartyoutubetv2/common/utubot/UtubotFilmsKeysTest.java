package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.view.KeyEvent;

import org.junit.Test;

import static com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsKeys.Result;
import static org.junit.Assert.assertEquals;

public class UtubotFilmsKeysTest {
    private static Result back(int action, int repeat, boolean overlay, boolean playing) {
        return UtubotFilmsKeys.resolveBack(KeyEvent.KEYCODE_BACK, action, repeat, overlay, playing);
    }

    @Test
    public void backWithTheStreamListUpWhilePlayingClosesTheListAndKeepsPlaying() {
        assertEquals(Result.HIDE_OVERLAY, back(KeyEvent.ACTION_DOWN, 0, true, true));
    }

    @Test
    public void backWithNoOverlayLeavesTheScreen() {
        assertEquals(Result.LEAVE, back(KeyEvent.ACTION_DOWN, 0, false, true));
    }

    @Test
    public void backOnTheListBeforeAnythingPlaysLeavesTheScreen() {
        assertEquals(Result.LEAVE, back(KeyEvent.ACTION_DOWN, 0, true, false));
    }

    @Test
    public void theReleaseAndARepeatOfBackDoNothing() {
        assertEquals(Result.CONSUME, back(KeyEvent.ACTION_UP, 0, true, true));
        assertEquals(Result.CONSUME, back(KeyEvent.ACTION_DOWN, 1, false, true));
    }

    @Test
    public void escapeActsLikeBackAndOtherKeysAreNotOurs() {
        assertEquals(Result.HIDE_OVERLAY, UtubotFilmsKeys.resolveBack(KeyEvent.KEYCODE_ESCAPE, KeyEvent.ACTION_DOWN, 0, true, true));
        assertEquals(Result.NONE, UtubotFilmsKeys.resolveBack(KeyEvent.KEYCODE_DPAD_UP, KeyEvent.ACTION_DOWN, 0, true, true));
    }
}
