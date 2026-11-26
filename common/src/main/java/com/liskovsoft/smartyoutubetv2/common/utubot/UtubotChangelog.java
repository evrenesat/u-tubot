package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

/**
 * The two version histories of the backend (`GET /v1/changelog?kind=app|backend`, ai/CONTRACT.md): the app's versions with their
 * release time and notes, and the backend's deploys with their time and what changed. Shown on the TV as plain, scrolling text.
 */
public final class UtubotChangelog {
    public static final String KIND_APP = "app";
    public static final String KIND_BACKEND = "backend";
    private static final String GROUP_FEATURES = "features";
    private static final String GROUP_FIXES = "fixes";
    private static final String DATE_FORMAT = "yyyy-MM-dd HH:mm";

    public static final class Entry {
        public final String version;
        /** 0: unknown */
        public final long atMs;
        /** [group, text] pairs in the order of the backend */
        public final List<String[]> changes;

        public Entry(String version, long atMs, List<String[]> changes) {
            this.version = version;
            this.atMs = atMs;
            this.changes = Collections.unmodifiableList(changes);
        }
    }

    private UtubotChangelog() {
    }

    /**
     * The entries of an answer, newest first as the backend sends them
     */
    public static List<Entry> parse(String json) throws JSONException {
        JSONArray items = new JSONObject(json).optJSONArray("entries");
        List<Entry> entries = new ArrayList<>();

        for (int i = 0; items != null && i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);

            if (item == null || item.optString("version", "").isEmpty()) {
                continue;
            }

            List<String[]> changes = new ArrayList<>();
            JSONArray array = item.optJSONArray("changes");

            for (int j = 0; array != null && j < array.length(); j++) {
                JSONObject change = array.optJSONObject(j);
                String text = change != null ? change.optString("text", "").trim() : "";

                if (!text.isEmpty()) {
                    changes.add(new String[]{change.optString("group", "other"), text});
                }
            }

            entries.add(new Entry(item.getString("version"), (long) (item.optDouble("at", 0) * 1000), changes));
        }

        return entries;
    }

    /**
     * The time of a release or deploy, e.g. 2026-11-25 10:00, in the device's time zone; empty when unknown
     */
    public static String formatTime(long atMs, TimeZone zone) {
        if (atMs <= 0) {
            return "";
        }

        SimpleDateFormat format = new SimpleDateFormat(DATE_FORMAT, Locale.US);
        format.setTimeZone(zone);

        return format.format(new Date(atMs));
    }

    /**
     * The row of the list: version and time
     */
    public static String title(String label, Entry entry, TimeZone zone) {
        String time = formatTime(entry.atMs, zone);

        return time.isEmpty() ? label + " " + entry.version : label + " " + entry.version + " - " + time;
    }

    /**
     * What the text view shows: the time, then the changes under New, Fixed and Other
     */
    public static String text(Entry entry, TimeZone zone, String none) {
        StringBuilder text = new StringBuilder();
        String time = formatTime(entry.atMs, zone);

        if (!time.isEmpty()) {
            text.append(time).append("\n\n");
        }

        if (entry.changes.isEmpty()) {
            return text.append(none).toString();
        }

        appendGroup(text, entry, GROUP_FEATURES, "New");
        appendGroup(text, entry, GROUP_FIXES, "Fixed");
        appendGroup(text, entry, null, "Other");

        return text.toString().trim();
    }

    private static void appendGroup(StringBuilder text, Entry entry, String group, String heading) {
        boolean isHeadingWritten = false;

        for (String[] change : entry.changes) {
            boolean isMine = group != null ? group.equals(change[0]) : !GROUP_FEATURES.equals(change[0]) && !GROUP_FIXES.equals(change[0]);

            if (!isMine) {
                continue;
            }

            if (!isHeadingWritten) {
                text.append(heading).append("\n");
                isHeadingWritten = true;
            }

            text.append("- ").append(change[1]).append("\n");
        }

        if (isHeadingWritten) {
            text.append("\n");
        }
    }

    /**
     * The entry of an installed version name, e.g. 0.3.5; null when the history has none
     */
    public static Entry find(List<Entry> entries, String versionName) {
        for (Entry entry : entries) {
            if (entry.version.equals(versionName)) {
                return entry;
            }
        }

        return null;
    }
}
