package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The director's-cut requests this TV ordered and is still waiting for (issue 96): the cuts that may become ready while the viewer is
 * somewhere else. It is kept on the device, because the app may be closed while the backend builds the cut. The list holds this
 * device's own orders only; another user's or the phone's requests never enter it.
 */
public final class UtubotCutWaitlist {
    /** A cut build longer than this is old: the app stops following it and the picker still shows its state next time */
    public static final long MAX_AGE_MS = 30 * 60 * 1000L;
    public static final int MAX_ENTRIES = 20;
    private static final String PREFS_NAME = "utubot_cut_waiting";
    private static final String KEY_ENTRIES = "entries";
    private final Store mStore;
    private final List<Entry> mEntries;

    public interface Store {
        List<Entry> load();

        void save(List<Entry> entries);
    }

    /** One ordered cut: enough to ask where it stands and to open its video when it is ready */
    public static final class Entry {
        public final String requestId;
        public final String videoId;
        @Nullable public final String title;
        /** Milliseconds since the epoch, when this device ordered the cut */
        public final long orderedAtMs;

        public Entry(String requestId, String videoId, @Nullable String title, long orderedAtMs) {
            this.requestId = requestId;
            this.videoId = videoId;
            this.title = title;
            this.orderedAtMs = orderedAtMs;
        }
    }

    public UtubotCutWaitlist(Store store) {
        mStore = store;
        mEntries = new ArrayList<>(store.load());
    }

    public static UtubotCutWaitlist prefs(Context context) {
        return new UtubotCutWaitlist(prefsStore(context));
    }

    public synchronized List<Entry> entries() {
        return new ArrayList<>(mEntries);
    }

    public synchronized void add(Entry entry) {
        if (entry == null || entry.requestId == null || entry.videoId == null) {
            return;
        }

        remove(entry.requestId);

        while (mEntries.size() >= MAX_ENTRIES) {
            mEntries.remove(0);
        }

        mEntries.add(entry);
        save();
    }

    public synchronized void remove(@Nullable String requestId) {
        if (requestId == null) {
            return;
        }

        for (int i = mEntries.size() - 1; i >= 0; i--) {
            if (requestId.equals(mEntries.get(i).requestId)) {
                mEntries.remove(i);
                save();
                return;
            }
        }
    }

    public synchronized void clear() {
        if (mEntries.isEmpty()) {
            return;
        }

        mEntries.clear();
        save();
    }

    private void save() {
        mStore.save(new ArrayList<>(mEntries));
    }

    private static Store prefsStore(Context context) {
        SharedPreferences prefs = context.getApplicationContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);

        return new Store() {
            @Override
            public List<Entry> load() {
                return decode(prefs.getString(KEY_ENTRIES, null));
            }

            @Override
            public void save(List<Entry> entries) {
                prefs.edit().putString(KEY_ENTRIES, encode(entries)).apply();
            }
        };
    }

    static String encode(List<Entry> entries) {
        JSONArray array = new JSONArray();

        for (Entry entry : entries) {
            JSONObject json = new JSONObject();

            try {
                json.put("id", entry.requestId);
                json.put("video", entry.videoId);
                json.put("title", entry.title != null ? entry.title : JSONObject.NULL);
                json.put("at", entry.orderedAtMs);
            } catch (JSONException e) {
                continue;
            }

            array.put(json);
        }

        return array.toString();
    }

    static List<Entry> decode(@Nullable String raw) {
        if (raw == null || raw.isEmpty()) {
            return Collections.emptyList();
        }

        List<Entry> entries = new ArrayList<>();

        try {
            JSONArray array = new JSONArray(raw);

            for (int i = 0; i < array.length(); i++) {
                JSONObject json = array.optJSONObject(i);

                if (json == null) {
                    continue;
                }

                String requestId = json.has("id") && !json.isNull("id") ? json.optString("id") : null;
                String videoId = json.has("video") && !json.isNull("video") ? json.optString("video") : null;

                if (requestId == null || videoId == null) {
                    continue;
                }

                String title = json.has("title") && !json.isNull("title") ? json.optString("title") : null;
                entries.add(new Entry(requestId, videoId, title, json.optLong("at", 0)));
            }
        } catch (JSONException e) {
            return Collections.emptyList();
        }

        return entries;
    }
}
