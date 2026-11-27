package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress.Entry;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmsProgressTest {
    private static final long MINUTE = 60_000;
    private UtubotFilmsProgress mProgress;

    @Before
    public void setUp() {
        Context context = RuntimeEnvironment.application;
        context.getSharedPreferences("utubot_films_progress", Context.MODE_PRIVATE).edit().clear().commit();
        mProgress = new UtubotFilmsProgress(context);
    }

    @Test
    public void resumesWhereItStoppedAndNeverFromTheFirstSeconds() {
        mProgress.save("tt1", "movie", "tt1", "One", "", 0, 0, 40 * MINUTE, 100 * MINUTE, 1);
        mProgress.save("tt2", "movie", "tt2", "Two", "", 0, 0, 10_000, 100 * MINUTE, 1);

        assertEquals(40 * MINUTE, mProgress.get("tt1").resumeMs());
        assertEquals(0, mProgress.get("tt2").resumeMs());
        assertNull(mProgress.get("tt3"));
    }

    @Test
    public void timeLeftIsInWholeMinutesThenHours() {
        mProgress.save("tt1", "movie", "tt1", "One", "", 0, 0, 60 * MINUTE, 100 * MINUTE, 1);
        mProgress.save("tt2", "movie", "tt2", "Two", "", 0, 0, 35 * MINUTE, 100 * MINUTE, 1);

        assertEquals("40 min left", mProgress.get("tt1").timeLeft());
        assertEquals("1 h 5 min left", mProgress.get("tt2").timeLeft());
        assertEquals("2 h left", UtubotFilmsProgress.timeLeft(120 * MINUTE));
        assertEquals("1 min left", UtubotFilmsProgress.timeLeft(1_000));
        assertEquals("", UtubotFilmsProgress.timeLeft(0));
    }

    @Test
    public void aTitleNearTheEndIsWatchedAndLeavesTheContinueRow() {
        mProgress.save("tt1", "movie", "tt1", "One", "", 0, 0, 95 * MINUTE, 100 * MINUTE, 1);
        mProgress.save("tt2", "movie", "tt2", "Two", "", 0, 0, 20 * MINUTE, 100 * MINUTE, 2);

        assertTrue(mProgress.isWatched("tt1"));
        assertFalse(mProgress.isWatched("tt2"));
        assertEquals(0, mProgress.get("tt1").resumeMs());

        List<Entry> row = mProgress.continueWatching();

        assertEquals(1, row.size());
        assertEquals("tt2", row.get(0).id);
    }

    @Test
    public void aSeriesShowsOnlyItsLatestEpisodeNewestFirst() {
        mProgress.save("tt9:1:1", "series", "tt9", "Show", "", 1, 1, 20 * MINUTE, 45 * MINUTE, 1);
        mProgress.save("tt9:1:2", "series", "tt9", "Show", "", 1, 2, 10 * MINUTE, 45 * MINUTE, 3);
        mProgress.save("tt1", "movie", "tt1", "One", "", 0, 0, 20 * MINUTE, 100 * MINUTE, 2);

        List<Entry> row = mProgress.continueWatching();

        assertEquals(2, row.size());
        assertEquals("tt9:1:2", row.get(0).id);
        assertEquals("tt1", row.get(1).id);
    }
}
