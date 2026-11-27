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
    public static final int SCHEMA_VERSION = 2;
    /** The schema the first synced keys came with: a TV that synced before the schema had a number is at this one */
    static final int FIRST_SCHEMA = 1;
    public static final int REQUEST_TIMEOUT_MS = 5000;
    static final String OUTCOME_SUPERSEDED = "superseded";
    private static final String STATE_MIGRATED = "migrated";
    private static final String STATE_MIGRATED_SCHEMA = "migrated_schema";
    private static final String STATE_VERSION = "version";
    private static final String STATE_REVS = "revs";
    private static final String STATE_OUTBOX = "outbox";
    private static final String STATE_LAST_OK = "last_ok_ms";
    private static final String STATE_COPIED = "copied";
    private static final String COPY_PREFIX = "pre.";
    private static final String OUT_VALUE = "v";
    private static final String OUT_BASE = "base";

    /** What a synced value is made of */
    public enum Kind {
        BOOL, INT, STRING
    }

    /** The synced settings: schema key, preference key, kind and the schema version that brought it. In step with {@code ai/settings/schema.json} (a test compares). */
    public static final class Key {
        public final String key;
        public final String pref;
        public final Kind kind;
        public final int since;

        Key(String key, String pref, Kind kind, int since) {
            this.key = key;
            this.pref = pref;
            this.kind = kind;
            this.since = since;
        }
    }

    public static final Key[] KEYS = {
            new Key("ai.assess", "assess", Kind.BOOL, 1),
            new Key("ai.mark_only", "mark_only", Kind.BOOL, 1),
            new Key("ai.answer_in_menu", "answer_in_menu", Kind.BOOL, 1),
            new Key("ai.summary_panel", "summary_panel", Kind.BOOL, 1),
            new Key("ai.panel_delay_ms", "panel_delay_ms", Kind.INT, 1),
            new Key("ai.auto_captions", "auto_captions", Kind.BOOL, 1),
            new Key("ai.auto_cuts", "auto_cuts", Kind.BOOL, 1),
            new Key("ai.wait_ms", "wait_ms", Kind.INT, 1),
            new Key("updates.checks", "update_checks", Kind.BOOL, 2),
            new Key("ai.auto_scroll_speed", "auto_scroll_speed", Kind.INT, 2),
            new Key("ai.cut_jump", "cut_jump", Kind.STRING, 2),
            new Key("updates.interval_minutes", "update_interval_minutes", Kind.INT, 2),
            new Key("updates.development_mode", "development_mode", Kind.BOOL, 2),
            new Key("browse.refresh_minutes", "browse_refresh_minutes", Kind.INT, 2),
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
        /**
         * @param waitMs how long the server may hold the request while nothing changed (0: answer at once)
         */
        String get(int have, int schemaVersion, int waitMs) throws IOException;

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
            mState.edit().remove(STATE_MIGRATED).remove(STATE_MIGRATED_SCHEMA).remove(STATE_VERSION).remove(STATE_REVS).remove(STATE_OUTBOX).apply();
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
                        mSettings.setSyncedValue(key.pref, fromText(key, stored));
                    }
                }
            });

            return true;
        }
    }

    /** How a long poll ended */
    public enum Watch {
        /** The server has a newer version: run a round now */
        CHANGED,
        /** The server held the request for the whole wait and nothing changed: watch again */
        HELD,
        /** The server answered "unchanged" at once: it does not hold requests, so the timer polls instead */
        ANSWERED_AT_ONCE,
        /** Not paired, switched off, or the request failed: the timer decides when to look again */
        FAILED
    }

    /**
     * Holds a request at the server until its settings version differs from this TV's (the long poll), at most {@code waitMs}.
     * It takes nothing in: {@link Watch#CHANGED} means "run a round". A server that does not know the wait answers at once;
     * that shows in the time it took. Blocks; never call it on the main thread. It does not wait for a round in progress.
     */
    public Watch watch(int waitMs) {
        if (!isMigrated() || mIsOff || !mSettings.isConfigured() || mSettings.getToken().isEmpty()) {
            return Watch.FAILED;
        }

        long started = mClock.nowMs();

        try {
            JSONObject doc = new JSONObject(mTransport.get(mState.getInt(STATE_VERSION, 0), SCHEMA_VERSION, waitMs));

            if (!doc.optBoolean("unchanged")) {
                return Watch.CHANGED;
            }

            return mClock.nowMs() - started >= waitMs / 2 ? Watch.HELD : Watch.ANSWERED_AT_ONCE;
        } catch (UtubotClient.HttpException e) {
            if (e.code == 404) {
                mIsOff = true;
            }

            return Watch.FAILED;
        } catch (IOException | JSONException | RuntimeException e) {
            return Watch.FAILED;
        }
    }

    private int migratedSchema() {
        return mState.getInt(STATE_MIGRATED_SCHEMA, FIRST_SCHEMA);
    }

    private void round() throws IOException, JSONException {
        if (!isMigrated()) {
            firstSync();
            return;
        }

        if (migratedSchema() < SCHEMA_VERSION) {
            upgradeSync();
            return;
        }

        JSONObject outbox = outbox();

        if (outbox.length() > 0) {
            upload(outbox);
            return;
        }

        int version = mState.getInt(STATE_VERSION, 0);
        JSONObject doc = new JSONObject(mTransport.get(version, SCHEMA_VERSION, 0));

        if (doc.optBoolean("unchanged")) {
            return;
        }

        apply(doc, outbox());
        report();
    }

    private void firstSync() throws IOException, JSONException {
        copyBeforeFirstSync(0);
        JSONObject doc = new JSONObject(mTransport.post(migrationBody(0)));
        apply(doc, new JSONObject());
        mState.edit().putBoolean(STATE_MIGRATED, true).putInt(STATE_MIGRATED_SCHEMA, SCHEMA_VERSION).apply();
    }

    /**
     * The app brought new keys since this TV's first sync: send only those, with what the TV has, so the TV's own values win
     * over the server's defaults (section 7 again, for the new keys). The keys it synced before stay base-checked.
     */
    private void upgradeSync() throws IOException, JSONException {
        int from = migratedSchema();
        copyBeforeFirstSync(from);
        JSONObject doc = new JSONObject(mTransport.post(migrationBody(from).put("from_schema", from)));
        apply(doc, outbox());
        mState.edit().putInt(STATE_MIGRATED_SCHEMA, SCHEMA_VERSION).apply();
    }

    /** Every value of the keys newer than {@code fromSchema}, with the flag for "the user set it" */
    private JSONObject migrationBody(int fromSchema) throws JSONException {
        JSONArray changes = new JSONArray();

        for (Key key : KEYS) {
            if (key.since > fromSchema) {
                changes.put(change(key, mSettings.getSyncedValue(key.pref), 0).put("user_set", mSettings.isSyncedValueSet(key.pref)));
            }
        }

        return base().put("initial", true).put("applied_version", mState.getInt(STATE_VERSION, 0)).put("changes", changes);
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

            Object stored = key.kind == Kind.BOOL ? (Object) (Boolean) value : key.kind == Kind.INT ? (Object) ((Number) value).intValue() : (Object) (String) value;

            if (!stored.equals(mSettings.getSyncedValue(key.pref))) {
                mSettings.applyRemote(() -> mSettings.setSyncedValue(key.pref, stored));
            }

            revs.put(key.key, entry.optInt("rev"));
        }

        mState.edit().putString(STATE_REVS, revs.toString()).putInt(STATE_VERSION, doc.optInt("version", mState.getInt(STATE_VERSION, 0))).apply();
    }

    private static boolean hasType(Key key, Object value) {
        switch (key.kind) {
            case BOOL:
                return value instanceof Boolean;
            case INT:
                return value instanceof Number;
            default:
                return value instanceof String;
        }
    }

    private static Object fromText(Key key, String text) {
        switch (key.kind) {
            case BOOL:
                return Boolean.valueOf(text);
            case INT:
                return Integer.valueOf(text);
            default:
                return text;
        }
    }

    /** Keeps the values of the keys that are about to start syncing (the ones newer than {@code fromSchema}), once each */
    private void copyBeforeFirstSync(int fromSchema) {
        SharedPreferences.Editor edit = mCopy.edit();

        for (Key key : KEYS) {
            if (key.since > fromSchema && !mCopy.contains(COPY_PREFIX + key.pref)) {
                edit.putString(COPY_PREFIX + key.pref, String.valueOf(mSettings.getSyncedValue(key.pref)));
            }
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
