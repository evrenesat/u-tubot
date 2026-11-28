package com.liskovsoft.smartyoutubetv2.common.app.views;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmPlay;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.lang.reflect.Field;
import java.lang.ref.WeakReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;

/**
 * Two films in a row (#300): the player of the first leaves the stack of screens when it finishes, so starting the player for the next
 * one is not skipped as "already on top".
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class ViewManagerFilmReplayTest {
    public static class PlayerActivity extends Activity {
    }

    public static class DetailsActivity extends Activity {
    }

    @Test
    public void thePlayerOfAFilmLeavesTheStackWhenItFinishes() throws Exception {
        ViewManager manager = ViewManager.instance(RuntimeEnvironment.getApplication());
        manager.register(PlaybackView.class, PlayerActivity.class);

        for (int play = 0; play < 2; play++) {
            PlayerActivity player = Robolectric.buildActivity(PlayerActivity.class).create().get();
            manager.addTop(player);
            assertEquals(PlaybackView.class, manager.getTopView());

            setPlayingVideo(Video.fromFilm(new UtubotFilmPlay("tt1:1:" + play, "series", "tt1", "Show", null, 1, play, "https://h/e.mkv", "Show", 0, 0)));
            manager.startParentView(player);

            assertNotEquals("play " + play, PlaybackView.class, manager.getTopView());
        }
    }

    private static void setPlayingVideo(Video video) throws Exception {
        Field field = PlaybackPresenter.class.getDeclaredField("mVideo");
        field.setAccessible(true);
        field.set(PlaybackPresenter.instance(RuntimeEnvironment.getApplication()), new WeakReference<>(video));
    }
}
