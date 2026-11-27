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
}
