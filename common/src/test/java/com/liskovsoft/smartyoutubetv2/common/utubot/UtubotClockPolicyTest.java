package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.lang.ref.WeakReference;
import java.lang.reflect.Field;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotClockPolicyTest {
    private boolean mSavedClock;
    private boolean mSavedEnding;
    private boolean mSavedFilmClock;

    @Before
    public void setUp() {
        PlayerData data = PlayerData.instance(RuntimeEnvironment.getApplication());
        mSavedClock = data.isGlobalClockEnabled();
        mSavedEnding = data.isGlobalEndingTimeEnabled();
        mSavedFilmClock = UtubotSettings.instance(RuntimeEnvironment.getApplication()).isFilmClockEnabled();
    }

    @After
    public void tearDown() throws Exception {
        PlayerData data = PlayerData.instance(RuntimeEnvironment.getApplication());
        data.setGlobalClockEnabled(mSavedClock);
        data.setGlobalEndingTimeEnabled(mSavedEnding);
        UtubotSettings.instance(RuntimeEnvironment.getApplication()).setFilmClockEnabled(mSavedFilmClock);
        play(null);
    }

    private static void play(Video video) throws Exception {
        Field field = PlaybackPresenter.class.getDeclaredField("mVideo");
        field.setAccessible(true);
        field.set(PlaybackPresenter.instance(RuntimeEnvironment.getApplication()), video == null ? null : new WeakReference<>(video));
    }

    private static Video film() {
        return Video.fromFilm(new UtubotFilmPlay("tt1", "movie", "tt1", "Heat", null, 0, 0, "https://h/f.mkv", "Heat", 0, 0));
    }

    @Test
    public void aFilmStartsWithTheClockOffWhateverYouTubeIsSetTo() throws Exception {
        PlayerData data = PlayerData.instance(RuntimeEnvironment.getApplication());
        data.setGlobalClockEnabled(true);
        data.setGlobalEndingTimeEnabled(true);
        UtubotSettings.instance(RuntimeEnvironment.getApplication()).setFilmClockEnabled(false);
        play(film());

        assertFalse(UtubotClockPolicy.cornerClock(RuntimeEnvironment.getApplication(), data));
        assertFalse(UtubotClockPolicy.cornerEndingTime(RuntimeEnvironment.getApplication(), data));
        assertFalse(UtubotClockPolicy.timeLine(RuntimeEnvironment.getApplication()));
        assertFalse(UtubotClockPolicy.isOn(RuntimeEnvironment.getApplication(), data));
    }

    @Test
    public void theButtonKeepsOneChoiceForFilmsAndAnotherForYouTube() throws Exception {
        PlayerData data = PlayerData.instance(RuntimeEnvironment.getApplication());
        data.setGlobalClockEnabled(true);
        data.setGlobalEndingTimeEnabled(true);
        UtubotSettings.instance(RuntimeEnvironment.getApplication()).setFilmClockEnabled(false);

        play(film());
        assertTrue(UtubotClockPolicy.toggle(RuntimeEnvironment.getApplication(), data));
        assertTrue(UtubotClockPolicy.cornerClock(RuntimeEnvironment.getApplication(), data));
        assertTrue(UtubotClockPolicy.timeLine(RuntimeEnvironment.getApplication()));
        assertTrue(data.isGlobalClockEnabled()); // YouTube's choice is untouched

        play(null); // a video
        assertTrue(UtubotClockPolicy.isOn(RuntimeEnvironment.getApplication(), data));
        assertFalse(UtubotClockPolicy.toggle(RuntimeEnvironment.getApplication(), data));
        assertFalse(data.isGlobalClockEnabled());
        assertFalse(data.isGlobalEndingTimeEnabled());
        assertTrue(UtubotSettings.instance(RuntimeEnvironment.getApplication()).isFilmClockEnabled()); // the film's is untouched
    }

    @Test
    public void aVideoFollowsThePlayersSettings() {
        assertEquals(true, UtubotClockPolicy.corner(false, false, true));
        assertEquals(false, UtubotClockPolicy.corner(true, false, true));
        assertEquals(true, UtubotClockPolicy.corner(true, true, false));
    }
}
