package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.Choice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.External;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The entries of the film's subtitle picker: Off, the tracks of the file (the viewer's language first, then English), then the
 * subtitles from the internet in the order the backend gave (the viewer's language, then English, best release match first). The one
 * in use is marked, and the first of the internet ones is named the best match.
 */
public final class UtubotSubtitlePicker {
    private static final Map<String, String> LANGUAGES = new HashMap<>();

    static {
        String[][] codes = {{"eng", "en"}, {"tur", "tr"}, {"fre", "fr"}, {"fra", "fr"}, {"ger", "de"}, {"deu", "de"}, {"spa", "es"},
                {"ita", "it"}, {"por", "pt"}, {"pob", "pt"}, {"rus", "ru"}, {"ara", "ar"}, {"dut", "nl"}, {"nld", "nl"}, {"pol", "pl"},
                {"swe", "sv"}, {"nor", "no"}, {"dan", "da"}, {"fin", "fi"}, {"gre", "el"}, {"ell", "el"}, {"heb", "he"}, {"hin", "hi"},
                {"jpn", "ja"}, {"kor", "ko"}, {"chi", "zh"}, {"zho", "zh"}, {"rum", "ro"}, {"ron", "ro"}, {"hun", "hu"}, {"cze", "cs"},
                {"ces", "cs"}, {"ukr", "uk"}, {"bul", "bg"}, {"hrv", "hr"}, {"srp", "sr"}, {"vie", "vi"}, {"tha", "th"}, {"ind", "id"}};

        for (String[] pair : codes) {
            LANGUAGES.put(pair[0], pair[1]);
        }
    }

    private UtubotSubtitlePicker() {
    }

    /** A track of the file, as the player lists it */
    public static final class Embedded {
        public final String id;
        public final String language;
        public final String title;
        public final Object handle;

        public Embedded(String id, @Nullable String language, @Nullable String title, @Nullable Object handle) {
            this.id = id;
            this.language = language == null ? "" : language;
            this.title = title == null ? "" : title;
            this.handle = handle;
        }
    }

    public static final class Entry {
        public final String kind;
        public final String id;
        public final String lang;
        public final String label;
        public final boolean selected;
        public final boolean best;
        @Nullable
        public final Object handle;

        Entry(String kind, String id, String lang, String label, boolean selected, boolean best, @Nullable Object handle) {
            this.kind = kind;
            this.id = id;
            this.lang = lang;
            this.label = label;
            this.selected = selected;
            this.best = best;
            this.handle = handle;
        }
    }

    /**
     * @param viewerLanguage the viewer's subtitle language, two letters or empty
     * @param current what is in use now, null for none known (then Off is marked)
     */
    public static List<Entry> build(List<Embedded> embedded, List<External> external, @Nullable String viewerLanguage, @Nullable Choice current,
                                    String offLabel, String embeddedPrefix, String internetPrefix, String bestNote) {
        List<Entry> entries = new ArrayList<>();
        boolean off = current == null || Choice.OFF.equals(current.kind);
        entries.add(new Entry(Choice.OFF, "", "", offLabel, off, false, null));

        for (Embedded track : sortEmbedded(embedded, viewerLanguage)) {
            boolean selected = current != null && Choice.EMBEDDED.equals(current.kind) && track.id.equals(current.id);
            entries.add(new Entry(Choice.EMBEDDED, track.id, track.language, embeddedPrefix + describe(track), selected, false, track.handle));
        }

        for (int i = 0; i < external.size(); i++) {
            External item = external.get(i);
            boolean selected = current != null && Choice.EXTERNAL.equals(current.kind) && item.id.equals(current.id);
            boolean best = i == 0;
            entries.add(new Entry(Choice.EXTERNAL, item.id, item.lang, internetPrefix + languageName(item.lang) + (item.name.isEmpty() ? "" : " - " + item.name)
                    + (best ? " (" + bestNote + ")" : ""), selected, best, item));
        }

        return entries;
    }

    private static List<Embedded> sortEmbedded(List<Embedded> tracks, @Nullable String viewerLanguage) {
        List<Embedded> sorted = new ArrayList<>(tracks);
        String viewer = normalize(viewerLanguage);

        sorted.sort((a, b) -> Integer.compare(rank(a.language, viewer), rank(b.language, viewer)));

        return sorted;
    }

    private static int rank(String language, String viewer) {
        String lang = normalize(language);

        if (!viewer.isEmpty() && lang.equals(viewer)) {
            return 0;
        }

        return lang.equals("en") ? 1 : 2;
    }

    private static String describe(Embedded track) {
        String language = languageName(track.language);

        if (track.title.isEmpty() || track.title.equalsIgnoreCase(language) || normalize(track.title).equals(normalize(track.language))) {
            return language;
        }

        return language.isEmpty() ? track.title : language + " - " + track.title;
    }

    /** Two letters for a two or three letter code, else the code as it came; empty for none */
    public static String normalize(@Nullable String code) {
        if (code == null) {
            return "";
        }

        String lower = code.trim().toLowerCase(Locale.ROOT).replace('_', '-');
        String first = lower.contains("-") ? lower.substring(0, lower.indexOf('-')) : lower;

        return LANGUAGES.containsKey(first) ? LANGUAGES.get(first) : first;
    }

    public static String languageName(@Nullable String code) {
        String normalized = normalize(code);

        if (normalized.isEmpty() || normalized.equals("und")) {
            return "";
        }

        String name = new Locale(normalized).getDisplayLanguage(Locale.ENGLISH);

        return name.isEmpty() || name.equals(normalized) ? normalized : name;
    }

    /** The best release match: the first of the backend's list */
    @Nullable
    public static External bestExternal(List<External> external) {
        return external.isEmpty() ? null : external.get(0);
    }
}
