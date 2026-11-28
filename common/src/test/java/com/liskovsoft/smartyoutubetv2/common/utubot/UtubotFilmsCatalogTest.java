package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Episode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Item;

import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmsCatalogTest {
    @Test
    public void readsAListOfTitles() throws Exception {
        String body = "{\"metas\":[{\"id\":\"tt1\",\"type\":\"movie\",\"name\":\"One\",\"poster\":\"http://p/1.jpg\",\"releaseInfo\":\"2020\",\"imdbRating\":\"7.8\"},"
                + "{\"id\":\"\",\"name\":\"No id\"}]}";

        List<Item> items = UtubotFilmsCatalog.parseList(body, "movie");

        assertEquals(1, items.size());
        assertEquals("One", items.get(0).name);
        assertEquals("2020", items.get(0).year);
        assertEquals("2020  |  IMDb 7.8", items.get(0).facts());
    }

    @Test
    public void readsASeriesWithItsEpisodes() throws Exception {
        JSONObject meta = new JSONObject("{\"id\":\"tt9\",\"type\":\"series\",\"name\":\"Show\",\"runtime\":\"45 min\",\"videos\":["
                + "{\"season\":2,\"episode\":1,\"title\":\"B\"},{\"season\":1,\"episode\":2,\"title\":\"A2\"},{\"season\":1,\"episode\":1,\"title\":\"A1\"},"
                + "{\"season\":0,\"episode\":1,\"title\":\"Special\"}]}");

        Item show = UtubotFilmsCatalog.parseItem(meta, "series");

        assertTrue(show.isSeries());
        assertEquals(3, show.episodes.size());
        assertEquals(Arrays.asList(1, 2), UtubotFilmsCatalog.seasons(show.episodes));
        List<Episode> first = UtubotFilmsCatalog.episodesOf(show.episodes, 1);
        assertEquals("A1", first.get(0).title);
        assertEquals("tt9:1:2", first.get(1).videoId("tt9"));
    }

    @Test
    public void anEpisodeTitleDropsItsOwnEpisodeNumber() {
        assertEquals("Winter Is Coming", new Episode(1, 1, "Episode 1: Winter Is Coming").shortTitle());
        assertEquals("Pilot", new Episode(1, 2, "episode 2 - Pilot").shortTitle());
        assertEquals("", new Episode(1, 3, "Episode 3").shortTitle());
        assertEquals("Episodes of Doom", new Episode(1, 4, "Episodes of Doom").shortTitle());
    }

    @Test
    public void theRuntimeInMilliseconds() {
        assertEquals(148 * 60_000L, UtubotFilmsCatalog.runtimeMs("148 min"));
        assertEquals((2 * 60 + 28) * 60_000L, UtubotFilmsCatalog.runtimeMs("2h 28min"));
        assertEquals(148 * 60_000L, UtubotFilmsCatalog.runtimeMs("148"));
        assertEquals(0, UtubotFilmsCatalog.runtimeMs(""));
        assertEquals(0, UtubotFilmsCatalog.runtimeMs(null));
    }

    @Test
    public void detailsOpenOnTheFirstUnfinishedAiredEpisode() {
        java.util.List<UtubotFilmsCatalog.Episode> episodes = new java.util.ArrayList<>();
        for (int season = 1; season <= 2; season++) {
            for (int number = 1; number <= 4; number++) {
                episodes.add(new UtubotFilmsCatalog.Episode(season, number, "T", number == 4 && season == 2 ? Long.MAX_VALUE : 0));
            }
        }

        UtubotFilmsCatalog.Episode none = UtubotFilmsCatalog.firstUnwatched(episodes, 1000, e -> false);
        org.junit.Assert.assertEquals(1, none.season);
        org.junit.Assert.assertEquals(1, none.number);

        UtubotFilmsCatalog.Episode mid = UtubotFilmsCatalog.firstUnwatched(episodes, 1000, e -> e.season == 1 || e.number < 3);
        org.junit.Assert.assertEquals(2, mid.season);
        org.junit.Assert.assertEquals(3, mid.number);

        UtubotFilmsCatalog.Episode all = UtubotFilmsCatalog.firstUnwatched(episodes, 1000, e -> true);
        org.junit.Assert.assertEquals(1, all.season);
        org.junit.Assert.assertEquals(1, all.number);
    }
}
