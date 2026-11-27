package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.SharedPreferences;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * Keeps this TV's AI settings in step with the server (ai/WEB_SETTINGS_PLAN.md, section 4). Every feature still reads
 * {@link UtubotSettings}; this class only pulls the server's values into it and sends the user's own changes. It does no
 * network on the thread that calls {@link #onLocalChange}; {@link #syncOnce()} blocks and belongs on a background thread.
 * <p>
 * The first sync (section 7) sends every synced value the TV has, so what the TV shows does not change. After it a local
 * change goes to an outbox (one entry per key, the newest value, the revision of the first unsent change) that survives a
 * restart; a server that does not answer leaves every value as it was.
 */
public final class UtubotSettingsSync {
    public static final int SCHEMA_VERSION = 1;
    public static final int REQUEST_TIMEOUT_MS = 5000;
    static final String OUTCOME_SUPERSEDED = "superseded";
    private static final String STATE_MIGRATED = "migrated";
    private static final String STATE_VERSION = "version";
    private static final String STATE_REVS = "revs";
    private static final String STATE_OUTBOX = "outbox";
    private static final String STATE_LAST_OK = "last_ok_ms";
    private static final String STATE_COPIED = "copied";
    private static final String COPY_PREFIX = "pre.";
    private static final String OUT_VALUE = "v";
    private static final String OUT_BASE = "base";

    /** The synced settings: schema key, preference key and kind. In step with {@code ai/settings/schema.json} (a test compares). */
    public static final class Key {
        public final String key;
        public final String pref;
        public final boolean isBool;

        Key(String key, String pref, boolean isBool) {
            this.key = key;
            this.pref = pref;
            this.isBool = isBool;
        }
    }

    public static final Key[] KEYS = {
            new Key("ai.assess", "assess", true),
            new Key("ai.mark_only", "mark_only", true),
            new Key("ai.answer_in_menu", "answer_in_menu", true),
            new Key("ai.summary_panel", "summary_panel", true),
            new Key("ai.panel_delay_ms", "panel_delay_ms", false),
            new Key("ai.auto_captions", "auto_captions", true),
            new Key("ai.auto_cuts", "auto_cuts", true),
            new Key("ai.wait_ms", "wait_ms", false),
    };

    public enum Status {
        /** The last sync worked */
        SYNCED,
        /** The server did not answer; changes are kept on the TV */
        FAILED,
        /** The server has no web settings (404): nothing to show */
        OFF,
        /** No backend address or token */
        NOT_PAIRED
    }

    public interface Transport {
        String get(int have, int schemaVersion) throws IOException;

        String post(JSONObject body) throws IOException;
    }

    public interface Clock {
        long nowMs();
    }

    private final UtubotSettings mSettings;
    private final SharedPreferences mState;
    private final SharedPreferences mCopy;
    private final Transport mTransport;
    private final Clock mClock;
    private final String mAppVersion;
    /** Held for a whole round, network included: never taken on the main thread */
    private final Object mSyncLock = new Object();
    /** Held for a moment, to read and write the outbox */
    private final Object mOutboxLock = new Object();
    private final List<String> mSuperseded = new ArrayList<>();
    private volatile Status mStatus = Status.SYNCED;
    private volatile boolean mIsOff;

    public UtubotSettingsSync(UtubotSettings settings, SharedPreferences state, SharedPreferences copy, Transport transport, Clock clock,
                              @Nullable String appVersion) {
        mSettings = settings;
        mState = state;
        mCopy = copy;
        mTransport = transport;
        mClock = clock;
        mAppVersion = appVersion;
    }

    public boolean isMigrated() {
        return mState.getBoolean(STATE_MIGRATED, false);
    }

    public Status getStatus() {
        return mStatus;
    }

    public long getLastOkMs() {
        return mState.getLong(STATE_LAST_OK, 0);
    }

    /**
     * The keys whose change on the web replaced this TV's offline change since the last call (schema keys), once each
     */
    public List<String> takeSuperseded() {
        synchronized (mOutboxLock) {
            List<String> out = new ArrayList<>(mSuperseded);
            mSuperseded.clear();
            return out;
        }
    }

    public boolean hasPendingChanges() {
        return outbox().length() > 0;
    }

    /**
     * The user changed a synced setting here. Applied already; this only notes it for the next upload. Before the first sync
     * nothing is noted: the first sync sends every value anyway.
     */
    public void onLocalChange(String prefKey) {
        Key key = keyOfPref(prefKey);

        if (key == null || !isMigrated()) {
            return;
        }

        synchronized (mOutboxLock) {
            try {
                JSONObject outbox = outbox();
                JSONObject previous = outbox.optJSONObject(key.key);
                int base = previous != null ? previous.optInt(OUT_BASE) : revs().optInt(key.key);
                outbox.put(key.key, new JSONObject().put(OUT_VALUE, mSettings.getSyncedValue(prefKey)).put(OUT_BASE, base));
                mState.edit().putString(STATE_OUTBOX, outbox.toString()).apply();
            } catch (JSONException e) {
                // A value that cannot be written down is not sent; the TV keeps it
            }
        }
    }

    /**
     * One round: the first sync, an upload of the outbox, or a pull. Blocks; never call it on the main thread.
     */
    public Status syncOnce() {
        synchronized (mSyncLock) {
            if (!mSettings.isConfigured() || mSettings.getToken().isEmpty()) {
                return mStatus = Status.NOT_PAIRED;
            }

            if (mIsOff) {
                return mStatus = Status.OFF;
            }

            try {
                round();
                mState.edit().putLong(STATE_LAST_OK, mClock.nowMs()).apply();

                return mStatus = Status.SYNCED;
            } catch (UtubotClient.HttpException e) {
                if (e.code == 404) {
                    mIsOff = true;
                    return mStatus = Status.OFF;
                }

                return mStatus = Status.FAILED;
            } catch (IOException | JSONException | RuntimeException e) {
                return mStatus = Status.FAILED;
            }
        }
    }

    /**
     * A new backend or token: ask again, and start from that server's values after a new first sync
     */
    public void onConnectionChanged() {
        synchronized (mSyncLock) {
            mIsOff = false;
            mState.edit().remove(STATE_MIGRATED).remove(STATE_VERSION).remove(STATE_REVS).remove(STATE_OUTBOX).apply();
        }
    }

    /**
     * Puts back the values the TV had before its first sync (the copy made then). Not shown in a menu.
     */
    public boolean restorePreSyncValues() {
        synchronized (mSyncLock) {
            if (!mCopy.getBoolean(STATE_COPIED, false)) {
                return false;
            }

            mSettings.applyRemote(() -> {
                for (Key key : KEYS) {
                    String stored = mCopy.getString(COPY_PREFIX + key.pref, null);

                    if (stored != null) {
                        mSettings.setSyncedValue(key.pref, key.isBool ? (Object) Boolean.valueOf(stored) : (Object) Integer.valueOf(stored));
                    }
                }
            });

            return true;
        }
    }

    private void round() throws IOException, JSONException {
        if (!isMigrated()) {
            firstSync();
            return;
        }

        JSONObject outbox = outbox();

        if (outbox.length() > 0) {
            upload(outbox);
            return;
        }

        int version = mState.getInt(STATE_VERSION, 0);
        JSONObject doc = new JSONObject(mTransport.get(version, SCHEMA_VERSION));

        if (doc.optBoolean("unchanged")) {
            return;
        }

        apply(doc, outbox());
        report();
    }

    private void firstSync() throws IOException, JSONException {
        copyBeforeFirstSync();
        JSONArray changes = new JSONArray();

        for (Key key : KEYS) {
            changes.put(change(key, mSettings.getSyncedValue(key.pref), 0).put("user_set", mSettings.isSyncedValueSet(key.pref)));
        }

        JSONObject body = base().put("initial", true).put("applied_version", mState.getInt(STATE_VERSION, 0)).put("changes", changes);
        JSONObject doc = new JSONObject(mTransport.post(body));
        apply(doc, new JSONObject());
        mState.edit().putBoolean(STATE_MIGRATED, true).apply();
    }

    private void upload(JSONObject sent) throws IOException, JSONException {
        JSONArray changes = new JSONArray();
        Iterator<String> keys = sent.keys();

        while (keys.hasNext()) {
            String key = keys.next();
            JSONObject entry = sent.getJSONObject(key);
            changes.put(new JSONObject().put("key", key).put("value", entry.get(OUT_VALUE)).put("base_rev", entry.optInt(OUT_BASE)));
        }

        JSONObject body = base().put("applied_version", mState.getInt(STATE_VERSION, 0)).put("changes", changes);
        JSONObject doc = new JSONObject(mTransport.post(body));
        JSONArray results = doc.optJSONArray("results");
        JSONObject current;

        synchronized (mOutboxLock) {
            current = outbox();

            for (int i = 0; results != null && i < results.length(); i++) {
                JSONObject result = results.getJSONObject(i);
                String key = result.optString("key");
                JSONObject now = current.optJSONObject(key);
                JSONObject was = sent.optJSONObject(key);

                if (result.optString("outcome").equals(OUTCOME_SUPERSEDED) && !mSuperseded.contains(key)) {
                    mSuperseded.add(key);
                }

                // A change made while the request was in flight stays for the next round
                if (now != null && was != null && now.toString().equals(was.toString())) {
                    current.remove(key);
                }
            }

            mState.edit().putString(STATE_OUTBOX, current.toString()).apply();
        }

        apply(doc, current);
    }

    /** Tell the server what this TV has applied, so its page can say "Applied" */
    private void report() throws IOException, JSONException {
        mTransport.post(base().put("applied_version", mState.getInt(STATE_VERSION, 0)).put("changes", new JSONArray()));
    }

    private JSONObject base() throws JSONException {
        JSONObject body = new JSONObject().put("schema_version", SCHEMA_VERSION);

        if (mAppVersion != null) {
            body.put("app_version", mAppVersion);
        }

        return body;
    }

    private JSONObject change(Key key, Object value, int baseRev) throws JSONException {
        return new JSONObject().put("key", key.key).put("value", value).put("base_rev", baseRev);
    }

    /** Takes the server's values into the settings, except the keys that wait in the outbox */
    private void apply(JSONObject doc, JSONObject waiting) throws JSONException {
        JSONObject values = doc.optJSONObject("settings");

        if (values == null) {
            return;
        }

        JSONObject revs = revs();

        for (Key key : KEYS) {
            JSONObject entry = values.optJSONObject(key.key);
            Object value = entry != null ? entry.opt("v") : null;

            if (entry == null || waiting.has(key.key) || !hasType(key, value)) {
                continue;
            }

            Object stored = key.isBool ? (Object) (Boolean) value : (Object) ((Number) value).intValue();

            if (!stored.equals(mSettings.getSyncedValue(key.pref))) {
                mSettings.applyRemote(() -> mSettings.setSyncedValue(key.pref, stored));
            }

            revs.put(key.key, entry.optInt("rev"));
        }

        mState.edit().putString(STATE_REVS, revs.toString()).putInt(STATE_VERSION, doc.optInt("version", mState.getInt(STATE_VERSION, 0))).apply();
    }

    private static boolean hasType(Key key, Object value) {
        return key.isBool ? value instanceof Boolean : value instanceof Number;
    }

    private void copyBeforeFirstSync() {
        if (mCopy.getBoolean(STATE_COPIED, false)) {
            return;
        }

        SharedPreferences.Editor edit = mCopy.edit();

        for (Key key : KEYS) {
            edit.putString(COPY_PREFIX + key.pref, String.valueOf(mSettings.getSyncedValue(key.pref)));
        }

        edit.putBoolean(STATE_COPIED, true).commit();
    }

    private JSONObject outbox() {
        return parse(mState.getString(STATE_OUTBOX, ""));
    }

    private JSONObject revs() {
        return parse(mState.getString(STATE_REVS, ""));
    }

    private static JSONObject parse(String json) {
        try {
            return json.isEmpty() ? new JSONObject() : new JSONObject(json);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }

    @Nullable
    private static Key keyOfPref(String pref) {
        for (Key key : KEYS) {
            if (key.pref.equals(pref)) {
                return key;
            }
        }

        return null;
    }
}
