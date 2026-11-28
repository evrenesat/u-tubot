package com.liskovsoft.smartyoutubetv2.common.utubot;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class UtubotFilmTitleTest {
    private static final String BLURAY = "Torrentio 1080p Movie.1080p.BluRay.x264.DTS-HD.5.1-GRP 👤 12 💾 11 GB";
    private static final long GB = 1024L * 1024 * 1024;

    private static UtubotFilmPlay film(String type, String name, int season, int episode, String stream, long size) {
        return new UtubotFilmPlay("id", type, "tt1", name, "", season, episode, "http://x", stream, 0, size);
    }

    @Test
    public void aFilmUsesTheCatalogueTitleAndYear() {
        UtubotFilmPlay film = film("movie", "The Long Voyage", 0, 0, BLURAY, 11 * GB);
        film.setCatalogue("2021", "");

        assertEquals("The Long Voyage (2021)", film.displayTitle());
    }

    @Test
    public void anEpisodeUsesTheSeriesNameCodeAndEpisodeTitle() {
        UtubotFilmPlay film = film("series", "Farscape", 1, 2, "Farscape.S01E02.1080p.WEB-DL.DDP5.1.x264-GRP", 0);
        film.setCatalogue("1999", "Back and Back and Back to the Future");

        assertEquals("Farscape — S01E02 — Back and Back and Back to the Future", film.displayTitle());
    }

    @Test
    public void anEpisodeWithoutACatalogueTitleKeepsTheCode() {
        assertEquals("Farscape — S02E10", film("series", "Farscape", 2, 10, "x", 0).displayTitle());
    }

    @Test
    public void theSecondLineHasShortChipsAndNoFileName() {
        assertEquals("1080p · DTS-HD 5.1 · 11 GB", UtubotFilmTitle.chips(BLURAY, 11 * GB));
        assertEquals("2160p · Dolby Vision P5 · Atmos · 58 GB",
                UtubotFilmTitle.chips("Movie.2160p.UHD.BluRay.REMUX.HEVC.DV.P5.TrueHD.Atmos-GRP", 58 * GB));
    }

    @Test
    public void theSizeFallsBackToTheAddonsText() {
        assertEquals("1080p · DTS-HD 5.1 · 11 GB", UtubotFilmTitle.chips(BLURAY, 0));
        assertEquals("720p · DD", UtubotFilmTitle.chips("Movie.720p.HDTV.x264.AC3-GRP", 0));
        assertEquals("1.5 GB", UtubotFilmTitle.size(1610612736L));
    }

    @Test
    public void withoutACatalogueNameTheFileNameIsParsed() {
        assertEquals("Movie", film("movie", "", 0, 0, BLURAY, 0).displayTitle());
        assertEquals("The Long Voyage (2021)",
                film("movie", "", 0, 0, "The.Long.Voyage.2021.1080p.BluRay.x264-GRP", 0).displayTitle());
        assertEquals("Farscape — S01E02", film("series", "", 0, 0, "Farscape.S01E02.Back.And.Back.720p.HDTV.x264-GRP", 0).displayTitle());
    }

    @Test
    public void realWorldNamesAreParsed() {
        assertParsed("Farscape", 1, 2, "", "Farscape.S01E02.Back.and.Back.and.Back.to.the.Future.1080p.BluRay.x264-GRP");
        assertParsed("Breaking Bad", 5, 14, "", "Breaking.Bad.5x14.720p.HDTV.x264-GRP");
        assertParsed("Blade Runner 2049", 0, 0, "2017", "Blade.Runner.2049.2017.2160p.UHD.BluRay.REMUX.HEVC.HDR.TrueHD.Atmos-GRP");
        assertParsed("1917", 0, 0, "2019", "1917.2019.1080p.WEB-DL.DDP5.1.Atmos.x264-GRP");
        assertParsed("The Wire", 3, 12, "2004", "The.Wire.2004.S03E12.1080p.BluRay.x265-GRP");
        assertParsed("Movie", 0, 0, "", "Torrentio\n1080p Movie.1080p.BluRay.x264.DTS-HD.5.1-GRP 👤 12 💾 11 GB");
        assertParsed("", 0, 0, "", null);
    }

    private static void assertParsed(String name, int season, int episode, String year, String file) {
        UtubotFilmTitle.Parsed parsed = UtubotFilmTitle.parse(file);

        assertEquals(file, name, parsed.name);
        assertEquals(file, season, parsed.season);
        assertEquals(file, episode, parsed.episode);
        assertEquals(file, year, parsed.year);
    }
}
