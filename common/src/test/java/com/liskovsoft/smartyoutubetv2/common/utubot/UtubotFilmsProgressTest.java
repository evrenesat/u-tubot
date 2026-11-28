package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress.Entry;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmsProgressTest {
    private static final long MINUTE = 60_000;
    private static final long NOW = 1_000_000_000L;
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

        List<UtubotFilmsProgress.Row> row = mProgress.continueRow(NOW);

        assertEquals(1, row.size());
        assertEquals("tt2", row.get(0).titleId);
    }

    @Test
    public void aSeriesShowsOnlyItsLatestEpisodeNewestFirst() {
        mProgress.save("tt9:1:1", "series", "tt9", "Show", "", 1, 1, 20 * MINUTE, 45 * MINUTE, 1);
        mProgress.save("tt9:1:2", "series", "tt9", "Show", "", 1, 2, 10 * MINUTE, 45 * MINUTE, 3);
        mProgress.save("tt1", "movie", "tt1", "One", "", 0, 0, 20 * MINUTE, 100 * MINUTE, 2);

        List<UtubotFilmsProgress.Row> row = mProgress.continueRow(NOW);

        assertEquals(2, row.size());
        assertEquals(2, row.get(0).episode);
        assertEquals("tt1", row.get(1).titleId);
    }

    private static List<UtubotFilmsCatalog.Episode> episodes() {
        return Arrays.asList(
                new UtubotFilmsCatalog.Episode(1, 1, "Premiere"),
                new UtubotFilmsCatalog.Episode(1, 2, "Episode 2: Back and Back"),
                new UtubotFilmsCatalog.Episode(2, 1, "Mind the Baby"),
                new UtubotFilmsCatalog.Episode(2, 2, "Not aired yet", NOW + 1_000_000));
    }

    private void finish(int season, int episode, long at) {
        mProgress.save("tt9:" + season + ":" + episode, "series", "tt9", "Show", "", season, episode, 44 * MINUTE, 45 * MINUTE, at);
    }

    @Test
    public void aFinishedEpisodeKeepsTheSeriesWithTheNextEpisode() {
        mProgress.rememberEpisodes("tt9", episodes());
        finish(1, 1, 1);

        List<UtubotFilmsProgress.Row> row = mProgress.continueRow(NOW);

        assertEquals(1, row.size());
        assertTrue(row.get(0).next);
        assertEquals(1, row.get(0).season);
        assertEquals(2, row.get(0).episode);
        assertEquals("Next: S01E02 Back and Back", row.get(0).subtitle());
        assertEquals(0f, row.get(0).share(), 0f);
    }

    @Test
    public void theNextEpisodeCrossesIntoTheNextSeason() {
        mProgress.rememberEpisodes("tt9", episodes());
        finish(1, 2, 1);

        UtubotFilmsProgress.Row row = mProgress.continueRow(NOW).get(0);

        assertEquals(2, row.season);
        assertEquals(1, row.episode);
    }

    @Test
    public void theSeriesLeavesAfterItsLastAiredEpisode() {
        mProgress.rememberEpisodes("tt9", episodes());
        finish(2, 1, 1);

        assertTrue(mProgress.continueRow(NOW).isEmpty());
    }

    @Test
    public void anUnfinishedEpisodeIsResumedNotSkipped() {
        mProgress.rememberEpisodes("tt9", episodes());
        finish(1, 1, 1);
        mProgress.save("tt9:1:2", "series", "tt9", "Show", "", 1, 2, 10 * MINUTE, 45 * MINUTE, 2);

        UtubotFilmsProgress.Row row = mProgress.continueRow(NOW).get(0);

        assertFalse(row.next);
        assertEquals(2, row.episode);
        assertEquals("S01E02 - 35 min left", row.subtitle());
    }

    @Test
    public void aRemovedSeriesStaysOutUntilWatchedAgain() {
        mProgress.rememberEpisodes("tt9", episodes());
        finish(1, 1, 10);
        mProgress.removeFromContinue("tt9", 20);

        assertTrue(mProgress.continueRow(NOW).isEmpty());

        finish(1, 2, 30);

        assertEquals(1, mProgress.continueRow(NOW).size());
        assertEquals(2, mProgress.continueRow(NOW).get(0).season);
    }

    @Test
    public void aFinishedFilmLeavesTheRowAndNeverComesBackAsNext() {
        mProgress.save("tt1", "movie", "tt1", "One", "", 0, 0, 99 * MINUTE, 100 * MINUTE, 1);

        assertTrue(mProgress.continueRow(NOW).isEmpty());
    }

    @Test
    public void withoutAnEpisodeListAFinishedEpisodeLeavesTheRow() {
        finish(1, 1, 1);

        assertTrue(mProgress.continueRow(NOW).isEmpty());
    }
}
