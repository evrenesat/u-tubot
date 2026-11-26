package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * Which screen an app-wide dialog goes over (issue 96): the last screen that is not a dialog, while the player keeps playing under it.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotScreenTest {
    private final List<Activity> mResumed = new ArrayList<>();

    @After
    public void tearDown() {
        for (Activity activity : mResumed) {
            UtubotScreen.onPaused(activity);
        }
    }

    @Test
    public void aScreenThatIsUp_isForegroundAndTakesTheDialog() {
        Activity screen = screen();

        assertTrue(UtubotScreen.isForeground());
        assertSame(screen, UtubotScreen.screenContext());
    }

    @Test
    public void aDialogOverThePlayer_leavesThePlayerAsTheScreenForADialog() {
        Activity player = screen();
        Activity dialog = dialog();

        assertTrue(UtubotScreen.isForeground());
        assertSame(player, UtubotScreen.screenContext());
    }

    @Test
    public void anotherScreenTakesTheDialog() {
        Activity first = screen();
        UtubotScreen.onPaused(first);
        Activity second = screen();

        assertSame(second, UtubotScreen.screenContext());
    }

    @Test
    public void whenEveryScreenIsPaused_theAppIsInTheBackground() {
        Activity player = screen();
        Activity dialog = dialog();

        UtubotScreen.onPaused(dialog);
        UtubotScreen.onPaused(player);

        assertFalse(UtubotScreen.isForeground());
        assertNull(UtubotScreen.screenContext());
    }

    @Test
    public void aPausedPlayer_fallsBackToTheDialogThatIsStillUp() {
        Activity player = screen();
        Activity dialog = dialog();

        UtubotScreen.onPaused(player);

        assertSame(dialog, UtubotScreen.screenContext());
        assertTrue(UtubotScreen.isForeground());
    }

    private Activity screen() {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        UtubotScreen.onResumed(activity, false);
        mResumed.add(activity);
        return activity;
    }

    private Activity dialog() {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        UtubotScreen.onResumed(activity, true);
        mResumed.add(activity);
        return activity;
    }
}
