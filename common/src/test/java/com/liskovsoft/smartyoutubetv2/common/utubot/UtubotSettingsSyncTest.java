package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.SharedPreferences;

import org.robolectric.RuntimeEnvironment;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * The settings sync (ai/WEB_SETTINGS_PLAN.md, T3) against a fake server: no network, no main thread work.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSettingsSyncTest {
    private static final int KEY_COUNT = UtubotSettingsSync.KEYS.length;
    private Context mContext;
    private UtubotSettings mSettings;
    private SharedPreferences mState;
    private SharedPreferences mCopy;
    private FakeServer mServer;
    private UtubotSettingsSync mSync;
    private long mNow = 1_000_000;

    /** What the real backend does, as far as the sync can tell: resolved values with revisions, results for changes */
    private static final class FakeServer implements UtubotSettingsSync.Transport {
        final Map<String, Object> values = new HashMap<>();
        final Map<String, Integer> revs = new HashMap<>();
        int version = 5;
        boolean isDown;
        int status;
        String garbage;
        final List<JSONObject> posts = new ArrayList<>();
        final AtomicInteger gets = new AtomicInteger();
        final Map<String, String> outcomes = new HashMap<>();
        final Map<String, Object> overrides = new HashMap<>();
        Thread lastThread;
        int lastWaitMs = -1;
        Runnable clockAdvanceOnUnchanged = () -> { };

        @Override
        public String get(int have, int schemaVersion, int waitMs) throws IOException {
            lastThread = Thread.currentThread();
            gets.incrementAndGet();
            lastWaitMs = waitMs;
            check();

            if (have == version) {
                clockAdvanceOnUnchanged.run();
                return "{\"version\":" + version + ",\"unchanged\":true}";
            }

            return document(null);
        }

        @Override
        public String post(JSONObject body) throws IOException {
            lastThread = Thread.currentThread();
            check();
            posts.add(body);
            JSONArray results = new JSONArray();
            JSONArray changes = body.optJSONArray("changes");
            boolean initial = body.optBoolean("initial");

            try {
                for (int i = 0; changes != null && i < changes.length(); i++) {
                    JSONObject change = changes.getJSONObject(i);
                    String key = change.getString("key");
                    String outcome = outcomes.containsKey(key) ? outcomes.get(key) : "applied";

                    if (outcome.equals("applied") && (initial || change.getInt("base_rev") == revs.get(key))) {
                        if (!change.get("value").equals(values.get(key))) {
                            version++;
                            overrides.put(key, change.get("value"));
                            values.put(key, change.get("value"));
                            revs.put(key, version);
                        }
                    }

                    results.put(new JSONObject().put("key", key).put("outcome", outcome));
                }

                return document(results);
            } catch (JSONException e) {
                throw new IOException(e);
            }
        }

        private void check() throws IOException {
            if (isDown) {
                throw new IOException("down");
            }

            if (status != 0) {
                throw new UtubotClient.HttpException(status, "HTTP " + status);
            }
        }

        private String document(JSONArray results) throws IOException {
            if (garbage != null) {
                return garbage;
            }

            try {
                JSONObject settings = new JSONObject();

                for (Map.Entry<String, Object> entry : values.entrySet()) {
                    settings.put(entry.getKey(), new JSONObject().put("v", entry.getValue()).put("rev", revs.get(entry.getKey())).put("from", "user"));
                }

                JSONObject doc = new JSONObject().put("version", version).put("settings", settings);

                if (results != null) {
                    doc.put("results", results);
                }

                return doc.toString();
            } catch (JSONException e) {
                throw new IOException(e);
            }
        }
    }

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.getApplication();
        mSettings = UtubotSettings.instance(mContext);
        StoredSettings.cleared(mSettings).commit();
        mSettings.setChangeListener(null);
        mSettings.setUrl("http://127.0.0.1:9");
        mSettings.setToken("t");
        mState = mContext.getSharedPreferences("test_sync_state", Context.MODE_PRIVATE);
        mCopy = mContext.getSharedPreferences("test_sync_copy", Context.MODE_PRIVATE);
        mState.edit().clear().commit();
        mCopy.edit().clear().commit();
        mServer = new FakeServer();
        resetServerValues();
        build();
    }

    @After
    public void tearDown() {
        mSettings.setChangeListener(null);
        StoredSettings.cleared(mSettings).commit();
    }

    private void build() {
        mSync = new UtubotSettingsSync(mSettings, mState, mCopy, mServer, () -> mNow, "1.0");
        mSettings.setChangeListener(mSync::onLocalChange);
    }

    private void resetServerValues() {
        mServer.values.clear();
        mServer.values.put("ai.assess", true);
        mServer.values.put("ai.mark_only", false);
        mServer.values.put("ai.answer_in_menu", true);
        mServer.values.put("ai.summary_panel", false);
        mServer.values.put("ai.panel_delay_ms", 1800);
        mServer.values.put("ai.auto_captions", true);
        mServer.values.put("ai.auto_cuts", false);
        mServer.values.put("ai.wait_ms", 1200);
        mServer.values.put("updates.checks", true);
        mServer.values.put("ai.auto_scroll_speed", 45);
        mServer.values.put("ai.cut_jump", "left_right");
        mServer.values.put("updates.interval_minutes", 5);
        mServer.values.put("updates.development_mode", mSettings.getSyncedValue("development_mode"));
        mServer.values.put("browse.refresh_minutes", 10);

        for (String key : mServer.values.keySet()) {
            mServer.revs.put(key, 0);
        }
    }

    private Map<String, Object> tvValues() {
        Map<String, Object> out = new HashMap<>();

        for (UtubotSettingsSync.Key key : UtubotSettingsSync.KEYS) {
            out.put(key.key, mSettings.getSyncedValue(key.pref));
        }

        return out;
    }

    private void syncFirst() {
        assertEquals(UtubotSettingsSync.Status.SYNCED, mSync.syncOnce());
        assertTrue(mSync.isMigrated());
    }

    @Test
    public void theFirstSyncKeepsEveryValueTheTvHad() {
        mSettings.setAssessEnabled(false);
        mSettings.setMarkOnly(true);
        mSettings.setAnswerInMenuEnabled(false);
        mSettings.setSummaryPanelEnabled(true);
        mSettings.setPanelDelayMs(700);
        mSettings.setAutoCaptionsEnabled(false);
        mSettings.setApplyReadyCutsEnabled(true);
        mSettings.setWaitMs(2500);
        Map<String, Object> before = tvValues();
        // The server holds other values for this user; for a first sync it takes the TV's as the TV's own
        mServer.values.put("ai.summary_panel", true);

        syncFirst();

        assertEquals(before, tvValues());
        int same = 0;

        for (Map.Entry<String, Object> entry : before.entrySet()) {
            if (entry.getValue().equals(mServer.values.get(entry.getKey()))) {
                same++;
            }
        }

        assertEquals(KEY_COUNT, same);
        assertTrue(mServer.posts.get(0).optBoolean("initial"));
        assertEquals(KEY_COUNT, mServer.posts.get(0).optJSONArray("changes").length());
        assertEquals(0, mServer.posts.get(0).optJSONArray("changes").optJSONObject(0).optInt("base_rev"));
    }

    @Test
    public void theFirstSyncFlagsOnlyTheValuesTheUserSet() {
        mSettings.setMarkOnly(true);

        syncFirst();

        JSONArray changes = mServer.posts.get(0).optJSONArray("changes");

        for (int i = 0; i < changes.length(); i++) {
            JSONObject change = changes.optJSONObject(i);
            assertEquals(change.optString("key"), change.optString("key").equals("ai.mark_only"), change.optBoolean("user_set"));
        }
    }

    @Test
    public void theFirstSyncMakesACopyOfTheValuesBeforeAnything() {
        mSettings.setMarkOnly(true);
        mSettings.setPanelDelayMs(700);

        syncFirst();

        assertEquals("true", mCopy.getString("pre.mark_only", null));
        assertEquals("700", mCopy.getString("pre.panel_delay_ms", null));
        mSettings.applyRemote(() -> {
            mSettings.setMarkOnly(false);
            mSettings.setPanelDelayMs(3000);
        });

        assertTrue(mSync.restorePreSyncValues());
        assertEquals(true, mSettings.getSyncedValue("mark_only"));
        assertEquals(700, mSettings.getSyncedValue("panel_delay_ms"));
    }

    @Test
    public void aPulledValueReachesTheGetterAndTheListeners() {
        syncFirst();
        AtomicInteger heard = new AtomicInteger();
        mSettings.addPanelListener(heard::incrementAndGet);
        mServer.values.put("ai.summary_panel", true);
        mServer.revs.put("ai.summary_panel", 9);
        mServer.version = 9;

        assertEquals(UtubotSettingsSync.Status.SYNCED, mSync.syncOnce());

        assertEquals(true, mSettings.getSyncedValue("summary_panel"));
        assertEquals(1, heard.get());
        assertFalse("a pulled value is not sent back", mSync.hasPendingChanges());
        JSONObject report = mServer.posts.get(mServer.posts.size() - 1);
        assertEquals(9, report.optInt("applied_version"));
        assertEquals(0, report.optJSONArray("changes").length());
    }

    @Test
    public void anUnchangedServerCostsOneSmallGet() {
        syncFirst();
        int posts = mServer.posts.size();

        mSync.syncOnce();
        mSync.syncOnce();

        assertEquals(posts, mServer.posts.size());
        assertEquals(2, mServer.gets.get());
    }

    @Test
    public void aLocalChangeIsAppliedBeforeAnyNetworkCall() {
        syncFirst();
        int gets = mServer.gets.get();
        int posts = mServer.posts.size();

        mSettings.setAutoCaptionsEnabled(false);

        assertEquals(false, mSettings.getSyncedValue("auto_captions"));
        assertEquals(gets, mServer.gets.get());
        assertEquals(posts, mServer.posts.size());
        assertTrue(mSync.hasPendingChanges());
    }

    @Test
    public void fiftyOfflineChangesOfOneKeyMakeOneUpload() {
        syncFirst();
        mServer.isDown = true;

        for (int i = 0; i < 50; i++) {
            mSettings.setPanelDelayMs(100 + i);
            assertEquals(UtubotSettingsSync.Status.FAILED, mSync.syncOnce());
        }

        mServer.isDown = false;
        int posts = mServer.posts.size();

        assertEquals(UtubotSettingsSync.Status.SYNCED, mSync.syncOnce());

        assertEquals(posts + 1, mServer.posts.size());
        JSONArray changes = mServer.posts.get(posts).optJSONArray("changes");
        assertEquals(1, changes.length());
        assertEquals(149, changes.optJSONObject(0).optInt("value"));
        assertEquals(0, changes.optJSONObject(0).optInt("base_rev"));
        assertFalse(mSync.hasPendingChanges());
    }

    @Test
    public void theOutboxSurvivesARestart() {
        syncFirst();
        mServer.isDown = true;
        mSettings.setApplyReadyCutsEnabled(true);
        mSync.syncOnce();

        build();
        mServer.isDown = false;

        assertTrue(mSync.hasPendingChanges());
        mSync.syncOnce();
        JSONArray changes = mServer.posts.get(mServer.posts.size() - 1).optJSONArray("changes");
        assertEquals("ai.auto_cuts", changes.optJSONObject(0).optString("key"));
        assertEquals(true, changes.optJSONObject(0).opt("value"));
    }

    @Test
    public void aSupersededAnswerAppliesTheServerValueAndSaysSoOnce() {
        syncFirst();
        mServer.isDown = true;
        mSettings.setSummaryPanelEnabled(true);
        mSync.syncOnce();
        mServer.isDown = false;
        mServer.values.put("ai.summary_panel", false);
        mServer.revs.put("ai.summary_panel", 8);
        mServer.version = 8;
        mServer.outcomes.put("ai.summary_panel", "superseded");

        mSync.syncOnce();

        assertEquals(false, mSettings.getSyncedValue("summary_panel"));
        assertEquals(Arrays.asList("ai.summary_panel"), mSync.takeSuperseded());
        assertTrue(mSync.takeSuperseded().isEmpty());
        assertFalse(mSync.hasPendingChanges());
    }

    @Test
    public void aWaitingLocalChangeIsNotOverwrittenByAPull() {
        syncFirst();
        mServer.isDown = true;
        mSettings.setWaitMs(2000);
        mSync.syncOnce();

        assertEquals(2000, mSettings.getSyncedValue("wait_ms"));
        mServer.isDown = false;
        mServer.values.put("ai.wait_ms", 900);
        mServer.version = 12;
        mServer.revs.put("ai.wait_ms", 12);
        mServer.outcomes.put("ai.wait_ms", "applied");
        // the upload goes first; the server takes it only when the base revision is right
        mSync.syncOnce();

        assertEquals(900, mSettings.getSyncedValue("wait_ms"));
    }

    @Test
    public void aServerThatIsDown404OrAnswersGarbageLeavesEveryValueAsItWas() {
        mSettings.setMarkOnly(true);
        mSettings.setPanelDelayMs(700);
        Map<String, Object> before = tvValues();

        mServer.isDown = true;
        assertEquals(UtubotSettingsSync.Status.FAILED, mSync.syncOnce());
        mServer.isDown = false;
        mServer.status = 401;
        assertEquals(UtubotSettingsSync.Status.FAILED, mSync.syncOnce());
        mServer.status = 500;
        assertEquals(UtubotSettingsSync.Status.FAILED, mSync.syncOnce());
        mServer.status = 0;
        mServer.garbage = "<html>not json";
        assertEquals(UtubotSettingsSync.Status.FAILED, mSync.syncOnce());
        mServer.garbage = "{\"version\":3,\"settings\":{\"ai.mark_only\":{\"v\":\"maybe\",\"rev\":1}}}";
        mSync.syncOnce();

        assertEquals(before, tvValues());
        assertFalse(mSync.isMigrated() && mSync.hasPendingChanges());
    }

    @Test
    public void a404SwitchesTheSyncOffUntilTheConnectionChanges() {
        mServer.status = 404;

        assertEquals(UtubotSettingsSync.Status.OFF, mSync.syncOnce());
        int calls = mServer.gets.get() + mServer.posts.size();
        mServer.status = 0;

        assertEquals(UtubotSettingsSync.Status.OFF, mSync.syncOnce());
        assertEquals(calls, mServer.gets.get() + mServer.posts.size());
        mSync.onConnectionChanged();
        assertEquals(UtubotSettingsSync.Status.SYNCED, mSync.syncOnce());
    }

    @Test
    public void anUnpairedTvDoesNotSync() {
        mSettings.setToken("");

        assertEquals(UtubotSettingsSync.Status.NOT_PAIRED, mSync.syncOnce());
        assertEquals(0, mServer.gets.get() + mServer.posts.size());
    }

    @Test
    public void aPulledValueOutsideTheRangeOrOfTheWrongTypeIsIgnored() {
        syncFirst();
        mServer.garbage = "{\"version\":20,\"settings\":{\"ai.panel_delay_ms\":{\"v\":99999999,\"rev\":3},\"ai.mark_only\":{\"v\":7,\"rev\":3}}}";

        mSync.syncOnce();

        assertEquals(1800, mSettings.getSyncedValue("panel_delay_ms"));
        assertEquals(false, mSettings.getSyncedValue("mark_only"));
    }

    @Test
    public void theTvDoesNotChangeBeforeItsFirstSyncJustBecauseSomethingWasSet() {
        mSettings.setMarkOnly(true);

        assertFalse(mSync.hasPendingChanges());
        assertNotNull(mSettings.getSyncedValue("mark_only"));
    }

    // ---- checkpoint 5: the per-TV keys, the schema upgrade and the long poll

    @Test
    public void aPulledPerTvValueReachesItsGetter() {
        syncFirst();
        mServer.values.put("updates.checks", false);
        mServer.values.put("ai.auto_scroll_speed", 60);
        mServer.values.put("ai.cut_jump", "off");
        mServer.values.put("updates.interval_minutes", 60);
        mServer.values.put("updates.development_mode", false);
        mServer.values.put("browse.refresh_minutes", 30);

        for (String key : mServer.values.keySet()) {
            mServer.revs.put(key, 12);
        }

        mServer.version = 12;
        assertEquals(UtubotSettingsSync.Status.SYNCED, mSync.syncOnce());

        assertFalse(mSettings.isUpdateChecksEnabled());
        assertEquals(60, mSettings.getAutoScrollSpeedPxPerSec());
        assertEquals(UtubotSettings.CUT_JUMP_OFF, mSettings.getCutJumpBinding());
        assertEquals(60, mSettings.getUpdateIntervalMinutes());
        assertFalse(mSettings.isDevelopmentMode());
        assertEquals(30, mSettings.getBrowseRefreshMinutes());
        assertFalse("a pulled value is not sent back", mSync.hasPendingChanges());
    }

    @Test
    public void aLocalPerTvChangeGoesToTheOutboxAndIsSentOnce() {
        syncFirst();

        mSettings.setUpdateIntervalMinutes(15);
        mSettings.setCutJumpBinding(UtubotSettings.CUT_JUMP_UP_DOWN);
        mSettings.setUpdateChecksEnabled(false);

        assertTrue(mSync.hasPendingChanges());
        mSync.syncOnce();

        JSONObject upload = mServer.posts.get(mServer.posts.size() - 1);
        Map<String, Object> sent = new HashMap<>();

        for (int i = 0; i < upload.optJSONArray("changes").length(); i++) {
            JSONObject change = upload.optJSONArray("changes").optJSONObject(i);
            sent.put(change.optString("key"), change.opt("value"));
        }

        assertEquals(15, sent.get("updates.interval_minutes"));
        assertEquals("up_down", sent.get("ai.cut_jump"));
        assertEquals(false, sent.get("updates.checks"));
        assertFalse(mSync.hasPendingChanges());
    }

    @Test
    public void aTvThatSyncedBeforeTheNewKeysKeepsItsOwnValuesForThem() {
        // Synced under schema 1: the state has no schema number
        syncFirst();
        mState.edit().remove("migrated_schema").commit();
        // an app of schema 1 had no copy of the newer keys
        SharedPreferences.Editor copy = mCopy.edit();

        for (UtubotSettingsSync.Key key : UtubotSettingsSync.KEYS) {
            if (key.since > 1) {
                copy.remove("pre." + key.pref);
            }
        }

        copy.commit();
        mSettings.applyRemote(() -> {
            mSettings.setUpdateIntervalMinutes(360);
            mSettings.setCutJumpBinding(UtubotSettings.CUT_JUMP_UP_DOWN);
            mSettings.setAutoScrollSpeedPxPerSec(60);
        });
        Map<String, Object> before = tvValues();
        int posts = mServer.posts.size();

        assertEquals(UtubotSettingsSync.Status.SYNCED, mSync.syncOnce());

        assertEquals(before, tvValues());
        JSONObject post = mServer.posts.get(posts);
        assertTrue(post.optBoolean("initial"));
        assertEquals(1, post.optInt("from_schema"));
        assertEquals(2, post.optInt("schema_version"));
        JSONArray changes = post.optJSONArray("changes");
        assertEquals(6, changes.length());

        for (int i = 0; i < changes.length(); i++) {
            JSONObject change = changes.optJSONObject(i);
            boolean set = change.optString("key").equals("updates.interval_minutes") || change.optString("key").equals("ai.cut_jump")
                    || change.optString("key").equals("ai.auto_scroll_speed");
            assertEquals(change.optString("key"), set, change.optBoolean("user_set"));
        }

        assertEquals(2, mState.getInt("migrated_schema", 0));
        assertEquals("360", mCopy.getString("pre.update_interval_minutes", null));
        // It happens once
        int after = mServer.posts.size();
        mSync.syncOnce();
        assertEquals(after, mServer.posts.size());
    }

    @Test
    public void aFreshTvSendsEveryKeyOnItsFirstSyncAndIsAtTheCurrentSchema() {
        syncFirst();

        assertEquals(UtubotSettingsSync.KEYS.length, mServer.posts.get(0).optJSONArray("changes").length());
        assertFalse(mServer.posts.get(0).has("from_schema"));
        assertEquals(UtubotSettingsSync.SCHEMA_VERSION, mState.getInt("migrated_schema", 0));
    }

    @Test
    public void theLongPollReportsAChangeAnUnchangedWaitAndAServerThatAnswersAtOnce() {
        syncFirst();
        mServer.clockAdvanceOnUnchanged = () -> mNow += 20_000;

        assertEquals(UtubotSettingsSync.Watch.HELD, mSync.watch(20_000));
        assertEquals(20_000, mServer.lastWaitMs);

        mServer.clockAdvanceOnUnchanged = () -> mNow += 40;
        assertEquals(UtubotSettingsSync.Watch.ANSWERED_AT_ONCE, mSync.watch(20_000));

        mServer.version++;
        assertEquals(UtubotSettingsSync.Watch.CHANGED, mSync.watch(20_000));
    }

    @Test
    public void theLongPollFailsQuietlyAndTakesNothingIn() {
        assertEquals("not synced yet: no watch", UtubotSettingsSync.Watch.FAILED, mSync.watch(1000));
        syncFirst();
        Map<String, Object> before = tvValues();
        mServer.version += 3;
        mServer.values.put("ai.summary_panel", true);

        assertEquals(UtubotSettingsSync.Watch.CHANGED, mSync.watch(1000));
        assertEquals("the watch only reports; the round applies", before, tvValues());

        mServer.isDown = true;
        assertEquals(UtubotSettingsSync.Watch.FAILED, mSync.watch(1000));
        mServer.isDown = false;
        mServer.status = 404;
        assertEquals(UtubotSettingsSync.Watch.FAILED, mSync.watch(1000));
        assertEquals(UtubotSettingsSync.Status.OFF, mSync.syncOnce());
    }
}
