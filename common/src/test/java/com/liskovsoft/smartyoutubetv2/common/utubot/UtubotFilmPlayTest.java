package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * A film played from a direct stream: the ids the cuts use, the progress it keeps and where it starts.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmPlayTest {
    private static final long MINUTE = 60_000;
    private UtubotFilmsProgress mProgress;

    @Before
    public void setUp() {
        Context context = RuntimeEnvironment.application;
        context.getSharedPreferences("utubot_films_progress", Context.MODE_PRIVATE).edit().clear().commit();
        mProgress = new UtubotFilmsProgress(context);
    }

    private static UtubotFilmPlay film(long startMs) {
        return new UtubotFilmPlay("tt1234567", "movie", "tt1234567", "Heat", "poster", 0, 0, "https://host/key/file.mkv", "Heat 2160p DV", startMs, 5_000);
    }

    private static UtubotFilmPlay episode() {
        return new UtubotFilmPlay("tt7654321:1:2", "series", "tt7654321", "Show", null, 1, 2, "https://host/e.mkv", "Show S01E02", 0, 0);
    }

    @Test
    public void aFilmSaysWhatSourceItIsForTheCuts() {
        UtubotFilmPlay film = film(0);

        assertEquals("film", film.sourceKind());
        assertEquals("imdb:tt1234567", film.sourceKey());
        assertEquals("Heat 2160p DV|5000", film.releaseKey());
        assertEquals(0, film.releaseDurationMs());

        film.setReleaseDurationMs(7_000_000);
        film.setReleaseDurationMs(0); // an unknown length does not wipe the known one
        assertEquals(7_000_000, film.releaseDurationMs());
    }

    @Test
    public void anEpisodeKeyHasSeasonAndEpisode() {
        UtubotFilmPlay episode = episode();

        assertEquals("imdb:tt7654321:S1E2", episode.sourceKey());
        assertEquals("Show S01E02", episode.releaseKey()); // no size known: the name alone
        assertEquals("Show  S1 E2", episode.title());
    }

    @Test
    public void theVideoOfAFilmIsNeverAYouTubeId() {
        Video video = Video.fromFilm(film(0));

        assertTrue(video.isFilm());
        assertEquals("utubot-film:tt1234567", video.videoId);
        assertEquals("Heat", video.getTitle());
        assertEquals("Heat 2160p DV", video.secondTitle);
        assertTrue(Video.from(video).isFilm());
        assertFalse(Video.from("dQw4w9WgXcQ").isFilm());
    }

    @Test
    public void progressGoesToTheFilmsStoreAndMarksWatchedNearTheEnd() {
        UtubotFilmPlay film = film(0);

        assertFalse("the length is not known yet", film.saveProgress(mProgress, 5 * MINUTE, 0, 1));
        assertTrue(film.saveProgress(mProgress, 40 * MINUTE, 100 * MINUTE, 1));
        assertEquals(40 * MINUTE, mProgress.get("tt1234567").resumeMs());
        assertFalse(mProgress.isWatched("tt1234567"));

        film.saveProgress(mProgress, 100 * MINUTE, 100 * MINUTE, 2);
        assertTrue(mProgress.isWatched("tt1234567"));
    }

    @Test
    public void itStartsFromTheOpenedStartThenFromTheStoredResume() {
        mProgress.save("tt1234567", "movie", "tt1234567", "Heat", "", 0, 0, 40 * MINUTE, 100 * MINUTE, 1);

        assertEquals(40 * MINUTE, film(0).resumeFrom(mProgress));
        assertEquals(12 * MINUTE, film(12 * MINUTE).resumeFrom(mProgress));
        assertEquals(0, episode().resumeFrom(mProgress));
    }

    @Test
    public void anotherStreamKeepsTheTitleAndStartsWhereTheViewerWas() {
        UtubotFilmPlay other = film(0).withStream("https://host/other.mkv", "Heat 1080p", 9_000, 33 * MINUTE);

        assertEquals("tt1234567", other.progressId);
        assertEquals("imdb:tt1234567", other.sourceKey());
        assertEquals("Heat 1080p|9000", other.releaseKey());
        assertEquals(33 * MINUTE, other.resumeFrom(mProgress));
    }
}
