package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotStremioClient.ImportedItem;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The imported watchlist store on this TV: it round-trips the mapped items and exposes the titles
 * (the "My list" row), the resume positions (the "Continue watching" row) and the watched marks.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmsWatchlistTest {
    private static final long MINUTE = 60_000;
    private UtubotFilmsWatchlist mWatchlist;

    @Before
    public void setUp() {
        Context context = RuntimeEnvironment.application;
        context.getSharedPreferences("utubot_films_watchlist", Context.MODE_PRIVATE).edit().clear().commit();
        mWatchlist = new UtubotFilmsWatchlist(context);
    }

    private static ImportedItem item(String id, String type, String titleId, String name, String poster, int season,
                                     int episode, long positionMs, boolean watched, long lastWatched) {
        return new ImportedItem(id, type, titleId, name, poster, season, episode, positionMs, watched, lastWatched);
    }

    @Test
    public void anEmptyStoreHasNoTitlesOrResume() {
        assertTrue(mWatchlist.titles().isEmpty());
        assertTrue(mWatchlist.resume().isEmpty());
        assertFalse(mWatchlist.isWatched("tt1"));
        assertEquals(0, mWatchlist.size());
    }

    @Test
    public void applyRoundTripsTheItems() {
        List<ImportedItem> items = Arrays.asList(
                item("tt1", "movie", "tt1", "One", "http://p/1.jpg", 0, 0, 0, false, 1),
                item("tt2", "movie", "tt2", "Two", "http://p/2.jpg", 0, 0, 0, false, 2));

        mWatchlist.apply(items);

        assertEquals(2, mWatchlist.size());
        assertEquals(2, mWatchlist.all().size());
        assertEquals("One", mWatchlist.titles().get(0).name);
        assertEquals("Two", mWatchlist.titles().get(1).name);
    }

    @Test
    public void titlesAreDistinctPerTitleIdAndPreferTheTitleLevelItem() {
        List<ImportedItem> items = Arrays.asList(
                item("tt9:1:1", "series", "tt9", "Show", "http://p/s.jpg", 1, 1, 0, true, 5),
                item("tt9", "series", "tt9", "Show", "http://p/s.jpg", 0, 0, 60 * MINUTE, false, 6),
                item("tt1", "movie", "tt1", "One", "http://p/1.jpg", 0, 0, 0, false, 1));

        mWatchlist.apply(items);

        List<ImportedItem> titles = mWatchlist.titles();

        assertEquals(2, titles.size());
        // the title-level series item is kept (not the episode)
        ImportedItem show = titles.get(0);
        assertEquals("tt9", show.id);
        assertEquals(0, show.season);
        assertEquals(0, show.episode);
    }

    @Test
    public void resumeIsTheUnfinishedTitlesNewestFirst() {
        List<ImportedItem> items = Arrays.asList(
                item("tt1", "movie", "tt1", "One", "http://p/1.jpg", 0, 0, 40 * MINUTE, false, 1),
                item("tt2", "movie", "tt2", "Two", "http://p/2.jpg", 0, 0, 20 * MINUTE, false, 3),
                item("tt3", "movie", "tt3", "Three", "http://p/3.jpg", 0, 0, 40 * MINUTE, false, 2),
                item("tt4", "movie", "tt4", "Four", "http://p/4.jpg", 0, 0, 10 * 1000, false, 4));

        mWatchlist.apply(items);

        List<ImportedItem> resume = mWatchlist.resume();

        // tt4 is below the resume minimum, the rest are newest first
        assertEquals(3, resume.size());
        assertEquals("tt2", resume.get(0).id);
        assertEquals("tt3", resume.get(1).id);
        assertEquals("tt1", resume.get(2).id);
    }

    @Test
    public void watchedMarksAreDetectedById() {
        List<ImportedItem> items = Arrays.asList(
                item("tt9:1:1", "series", "tt9", "Show", "http://p/s.jpg", 1, 1, 0, true, 5));

        mWatchlist.apply(items);

        assertTrue(mWatchlist.isWatched("tt9:1:1"));
        assertFalse(mWatchlist.isWatched("tt9:1:2"));
    }

    @Test
    public void aNewImportReplacesTheOldLibrary() {
        mWatchlist.apply(Arrays.asList(item("tt1", "movie", "tt1", "One", "", 0, 0, 0, false, 1)));
        mWatchlist.apply(Arrays.asList(item("tt2", "movie", "tt2", "Two", "", 0, 0, 0, false, 2)));

        assertEquals(1, mWatchlist.size());
        assertEquals("Two", mWatchlist.titles().get(0).name);
    }

    @Test
    public void anUnreadableStoreTreatedAsEmpty() {
        RuntimeEnvironment.application.getSharedPreferences("utubot_films_watchlist", Context.MODE_PRIVATE)
                .edit().putString("items", "{not json").commit();

        assertTrue(mWatchlist.all().isEmpty());
        assertTrue(mWatchlist.titles().isEmpty());
    }

    @Test
    public void aSeriesWithOnlyWatchedEpisodesStillShowsInTitles() {
        List<ImportedItem> items = Arrays.asList(
                item("tt9:1:1", "series", "tt9", "Show", "http://p/s.jpg", 1, 1, 0, true, 5));

        mWatchlist.apply(items);

        assertEquals(1, mWatchlist.titles().size());
        assertEquals("tt9", mWatchlist.titles().get(0).titleId);
        // the title-level item is absent, so the episode carries the title name and poster
        assertEquals("Show", mWatchlist.titles().get(0).name);
    }
}
