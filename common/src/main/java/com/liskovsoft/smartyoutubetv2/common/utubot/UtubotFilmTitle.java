package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * What the player shows for a film or an episode: the title from the catalogue ("The Long Voyage (2021)", "Farscape - S01E02 - Back and
 * Back and Back to the Future") and a second line of short format chips ("1080p - DTS-HD 5.1 - 11 GB"), never the release's file name.
 *
 * <p>The file name is read (episode code, year, quality) only as a fallback, when the catalogue gave no title, no episode or no year.
 */
public final class UtubotFilmTitle {
    public static final String SEPARATOR = " — ";
    public static final String CHIP_SEPARATOR = " · ";
    private static final long KIB = 1024;
    private static final long GIB = KIB * KIB * KIB;
    private static final long MIB = KIB * KIB;

    private static final Pattern EPISODE_CODE = Pattern.compile("(?i)(?<![a-z0-9])s(\\d{1,2})[ ._-]?e(\\d{1,3})(?![0-9])");
    private static final Pattern EPISODE_X = Pattern.compile("(?i)(?<![a-z0-9])(\\d{1,2})x(\\d{2,3})(?![0-9a-z])");
    private static final Pattern YEAR = Pattern.compile("(?<![0-9])((?:19|20)\\d{2})(?![0-9])");
    private static final Pattern RESOLUTION = Pattern.compile("(?i)(?<![a-z0-9])(2160|1440|1080|720|576|480)[pi](?![a-z0-9])|(?<![a-z0-9])(4k|uhd)(?![a-z0-9])");
    private static final Pattern EMOJI_SIZE = Pattern.compile("💾\\s*([0-9]+(?:[.,][0-9]+)?)\\s*(GB|MB)", Pattern.CASE_INSENSITIVE);

    private UtubotFilmTitle() {
    }

    /** What a release name says about the title, for the fallback */
    public static final class Parsed {
        public final String name;
        public final int season;
        public final int episode;
        public final String year;

        Parsed(String name, int season, int episode, String year) {
            this.name = name;
            this.season = season;
            this.episode = episode;
            this.year = year;
        }
    }

    /** "The.Long.Voyage.2021.1080p.BluRay.x264-GRP" gives "The Long Voyage", 2021; "Farscape.S01E02.720p" gives Farscape, 1, 2 */
    public static Parsed parse(@Nullable String fileName) {
        String text = fileName == null ? "" : cleanName(fileName);
        int season = 0;
        int episode = 0;
        int cut = text.length();

        Matcher code = EPISODE_CODE.matcher(text);
        Matcher x = EPISODE_X.matcher(text);

        if (code.find()) {
            season = Integer.parseInt(code.group(1));
            episode = Integer.parseInt(code.group(2));
            cut = Math.min(cut, code.start());
        } else if (x.find()) {
            season = Integer.parseInt(x.group(1));
            episode = Integer.parseInt(x.group(2));
            cut = Math.min(cut, x.start());
        }

        Matcher resolution = RESOLUTION.matcher(text);
        int quality = resolution.find() && resolution.start() > 0 ? resolution.start() : text.length();
        String year = "";
        int yearAt = -1;
        Matcher years = YEAR.matcher(text);

        while (years.find() && years.start() < quality) { // the last year before the quality: "Blade.Runner.2049.2017.2160p"
            if (years.start() > 0) { // a title that is a year ("1917") stays a title
                year = years.group(1);
                yearAt = years.start();
            }
        }

        if (yearAt > 0) {
            cut = Math.min(cut, yearAt);
        }

        cut = Math.min(cut, quality);

        String name = text.substring(0, cut).replaceAll("[._]+", " ").replaceAll("[\\s(\\[\\-]+$", "").trim();

        return new Parsed(name, season, episode, year);
    }

    /** The release name inside what an addon shows: its own label, the name, then seeders and size ("Torrentio 1080p Movie.1080p.x264-GRP 👤 12 💾 11 GB") */
    private static String cleanName(String raw) {
        String text = raw.replace('\n', ' ');
        int emoji = text.indexOf('\uD83D');

        if (emoji > 0) {
            text = text.substring(0, emoji);
        }

        String best = "";

        for (String token : text.trim().split("\\s+")) {
            if (token.split("\\.", -1).length > 2 && token.length() > best.length()) { // a dotted release name
                best = token;
            }
        }

        return best.isEmpty() ? text.trim() : best;
    }

    /**
     * The title line: from the catalogue when it has the name, else from the file name. A film is "Name (Year)", an episode "Name - S01E02 -
     * Episode title" (the code alone when the catalogue has no title for it).
     */
    public static String title(UtubotFilmPlay film) {
        Parsed parsed = film.name.isEmpty() || film.isSeries() && film.season <= 0 ? parse(film.streamName) : null;
        String name = !film.name.isEmpty() ? film.name : parsed != null && !parsed.name.isEmpty() ? parsed.name : film.streamName;

        if (film.isSeries()) {
            int season = film.season > 0 ? film.season : parsed != null ? parsed.season : 0;
            int episode = film.season > 0 ? film.episode : parsed != null ? parsed.episode : 0;

            if (season <= 0) {
                return name;
            }

            String result = name + SEPARATOR + String.format(Locale.US, "S%02dE%02d", season, episode);

            return film.episodeTitle().isEmpty() ? result : result + SEPARATOR + film.episodeTitle();
        }

        String year = !film.year().isEmpty() ? film.year() : parse(film.streamName).year;

        return year.isEmpty() ? name : name + " (" + year + ")";
    }

    /** The second line: "1080p - DTS-HD 5.1 - 11 GB", empty parts left out */
    public static String chips(@Nullable String streamName, long sizeBytes) {
        List<String> chips = chipList(streamName, sizeBytes);

        return String.join(CHIP_SEPARATOR, chips);
    }

    static List<String> chipList(@Nullable String streamName, long sizeBytes) {
        String name = streamName == null ? "" : streamName;
        UtubotFilmFormat format = UtubotFilmFormat.parse(name);
        List<String> chips = new ArrayList<>();
        String resolution = resolution(name);

        if (!resolution.isEmpty()) {
            chips.add(resolution);
        }

        if (!format.hdrLabel().isEmpty()) {
            chips.add(format.hdrLabel());
        }

        String audio = (format.audio + " " + format.channels).trim();

        if (!audio.isEmpty()) {
            chips.add(audio);
        }

        String size = size(sizeBytes > 0 ? sizeBytes : sizeFromName(name));

        if (!size.isEmpty()) {
            chips.add(size);
        }

        return chips;
    }

    static String resolution(String name) {
        Matcher matcher = RESOLUTION.matcher(name);

        if (!matcher.find()) {
            return "";
        }

        return matcher.group(1) != null ? matcher.group(1) + "p" : "4K";
    }

    private static long sizeFromName(String name) {
        Matcher matcher = EMOJI_SIZE.matcher(name);

        if (!matcher.find()) {
            return 0;
        }

        double value = Double.parseDouble(matcher.group(1).replace(',', '.'));

        return Math.round(value * ("GB".equalsIgnoreCase(matcher.group(2)) ? GIB : MIB));
    }

    static String size(long bytes) {
        if (bytes <= 0) {
            return "";
        }

        if (bytes >= GIB) {
            double gib = bytes / (double) GIB;

            return gib >= 10 ? Math.round(gib) + " GB" : String.format(Locale.US, "%.1f GB", gib);
        }

        return Math.max(1, Math.round(bytes / (double) MIB)) + " MB";
    }
}
