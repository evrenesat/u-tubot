package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The subtitles of a film from the internet: the list the backend builds from the Stremio OpenSubtitles add-on (the same client and cache
 * as the film cuts), the file as WebVTT, a shifted copy for the viewer's delay, and the choice kept per title.
 */
public final class UtubotFilmSubtitles {
    /** The id of the text track of an internet subtitle: a caption track id, so the track selector picks it by its id (see TrackSelectorManager), and not one of the HQ captions of a video */
    public static final String TRACK_PREFIX = UtubotCaptions.TRACK_ID_PREFIX + "film:";
    public static final long DELAY_LIMIT_MS = 60_000;
    private static final String DIR = "utubot_film_subtitles";
    private static final String PREFS = "utubot_film_subtitles";
    private static final Pattern VTT_TIME = Pattern.compile("(?:(\\d+):)?(\\d{2}):(\\d{2})\\.(\\d{3})");

    private UtubotFilmSubtitles() {
    }

    /** One subtitle the backend offers for the stream */
    public static final class External {
        public final String id;
        public final String lang;
        public final String name;
        public final double score;
        public final boolean best;

        public External(String id, String lang, String name, double score, boolean best) {
            this.id = id;
            this.lang = lang;
            this.name = name;
            this.score = score;
            this.best = best;
        }
    }

    /** What the viewer picked for a title: nothing, one of the file's tracks, or a subtitle from the internet, with its delay */
    public static final class Choice {
        public static final String OFF = "off";
        public static final String EMBEDDED = "embedded";
        public static final String EXTERNAL = "external";
        public final String kind;
        public final String id;
        public final String lang;
        public final long delayMs;

        public Choice(String kind, @Nullable String id, @Nullable String lang, long delayMs) {
            this.kind = kind;
            this.id = id == null ? "" : id;
            this.lang = lang == null ? "" : lang;
            this.delayMs = Math.max(-DELAY_LIMIT_MS, Math.min(DELAY_LIMIT_MS, delayMs));
        }

        public Choice withDelay(long delayMs) {
            return new Choice(kind, id, lang, delayMs);
        }

        public String encode() {
            return kind + "\t" + id + "\t" + lang + "\t" + delayMs;
        }

        @Nullable
        public static Choice decode(@Nullable String text) {
            if (text == null) {
                return null;
            }

            String[] parts = text.split("\t", -1);

            if (parts.length != 4 || !(OFF.equals(parts[0]) || EMBEDDED.equals(parts[0]) || EXTERNAL.equals(parts[0]))) {
                return null;
            }

            try {
                return new Choice(parts[0], parts[1], parts[2], Long.parseLong(parts[3]));
            } catch (NumberFormatException e) {
                return null;
            }
        }
    }

    /** The backend's list ({@code {"subtitles":[...]}}), in its order: the viewer's language, then English, best release match first */
    public static List<External> parse(String json) throws JSONException {
        List<External> list = new ArrayList<>();
        JSONArray items = new JSONObject(json).optJSONArray("subtitles");

        for (int i = 0; items != null && i < items.length(); i++) {
            JSONObject item = items.getJSONObject(i);
            String id = item.optString("id", "");

            if (!id.isEmpty()) {
                list.add(new External(id, item.optString("lang", ""), item.optString("name", ""), item.optDouble("score", 0), item.optBoolean("best", false)));
            }
        }

        return list;
    }

    /** A WebVTT file with every cue moved by {@code delayMs} (positive: later); a cue that ends up before the start is moved to zero */
    public static String shiftVtt(String vtt, long delayMs) {
        if (delayMs == 0) {
            return vtt;
        }

        StringBuilder out = new StringBuilder(vtt.length());

        for (String line : vtt.split("\n", -1)) {
            out.append(line.contains("-->") ? shiftLine(line, delayMs) : line).append('\n');
        }

        out.setLength(Math.max(0, out.length() - 1));

        return out.toString();
    }

    private static String shiftLine(String line, long delayMs) {
        Matcher matcher = VTT_TIME.matcher(line);
        StringBuffer out = new StringBuffer();

        while (matcher.find()) {
            long hours = matcher.group(1) == null ? 0 : Long.parseLong(matcher.group(1));
            long ms = ((hours * 60 + Long.parseLong(matcher.group(2))) * 60 + Long.parseLong(matcher.group(3))) * 1000 + Long.parseLong(matcher.group(4));
            matcher.appendReplacement(out, format(Math.max(0, ms + delayMs)));
        }

        matcher.appendTail(out);

        return out.toString();
    }

    static String format(long ms) {
        return String.format(java.util.Locale.US, "%02d:%02d:%02d.%03d", ms / 3_600_000, ms / 60_000 % 60, ms / 1000 % 60, ms % 1000);
    }

    /** Where a subtitle of a release is kept after it was downloaded, with its delay applied */
    public static File file(Context context, String releaseId, String subtitleId, long delayMs) {
        File dir = new File(new File(context.getCacheDir(), DIR), releaseId);

        return new File(dir, safe(subtitleId) + (delayMs == 0 ? "" : "." + delayMs) + ".vtt");
    }

    private static String safe(String text) {
        return text.replaceAll("[^A-Za-z0-9_.-]", "_");
    }

    /** The choice per title, on this TV */
    public static final class Store {
        private final SharedPreferences mPrefs;

        public Store(Context context) {
            mPrefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        }

        @Nullable
        public Choice get(String titleKey) {
            return Choice.decode(mPrefs.getString(titleKey, null));
        }

        public void set(String titleKey, Choice choice) {
            mPrefs.edit().putString(titleKey, choice.encode()).apply();
        }
    }
}
