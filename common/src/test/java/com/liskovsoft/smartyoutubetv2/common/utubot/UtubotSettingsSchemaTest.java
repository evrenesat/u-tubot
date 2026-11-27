package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * T1 of ai/WEB_SETTINGS_PLAN.md: a preference cannot be added to {@link UtubotSettings} without saying whether it follows the server.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSettingsSchemaTest {
    /** Never synced: the TV's identity, the connection, local state and developer tools (plan section 2.4) */
    private static final List<String> DEVICE_ONLY = Arrays.asList("url", "token", "update_url", "pair_prompt_done", "setup_prompt_done",
            "dismissed_update", "dismissed_update_code", "cut_legend_shown", "pending_prompt_sets", "films_developer", "films_skips", "films_imdb_id");

    private static String read(String relative) throws Exception {
        File file = new File(relative);

        if (!file.exists()) {
            file = new File("..", relative);
        }

        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    private static JSONArray schema() throws Exception {
        return new JSONObject(read("ai/settings/schema.json")).getJSONArray("settings");
    }

    @Test
    public void everyPreferenceIsInTheSchemaOrOnTheDeviceOnlyList() throws Exception {
        Matcher matcher = Pattern.compile("private static final String KEY_\\w+ = \"([a-z_]+)\";")
                .matcher(read("common/src/main/java/com/liskovsoft/smartyoutubetv2/common/utubot/UtubotSettings.java"));
        Set<String> keys = new HashSet<>();

        while (matcher.find()) {
            keys.add(matcher.group(1));
        }

        Set<String> prefs = new HashSet<>();
        JSONArray settings = schema();

        for (int i = 0; i < settings.length(); i++) {
            String pref = settings.getJSONObject(i).optString("tv_pref", "");

            if (!pref.isEmpty()) {
                prefs.add(pref);
            }
        }

        Set<String> unclassified = new HashSet<>(keys);
        unclassified.removeAll(prefs);
        unclassified.removeAll(DEVICE_ONLY);

        assertTrue("classify these in ai/settings/schema.json or the device-only list: " + unclassified, unclassified.isEmpty());
        assertTrue(keys.size() > 20);
    }

    @Test
    public void theSyncedKeysAreTheSchemasPhaseOneTvKeys() throws Exception {
        JSONArray settings = schema();
        int found = 0;

        for (int i = 0; i < settings.length(); i++) {
            JSONObject setting = settings.getJSONObject(i);
            boolean isTv = setting.getJSONArray("clients").toString().contains("\"tv\"");

            if (!isTv || setting.getInt("phase") != 1 || !setting.getString("remote").equals("rw")) {
                continue;
            }

            UtubotSettingsSync.Key key = UtubotSettingsSync.KEYS[found++];

            assertEquals(setting.getString("key"), key.key);
            assertEquals(setting.getString("tv_pref"), key.pref);
            assertEquals(setting.getString("type").equals("bool"), key.isBool);
            assertEquals(setting.get("default"), defaultOf(key));
        }

        assertEquals(UtubotSettingsSync.KEYS.length, found);
    }

    private static Object defaultOf(UtubotSettingsSync.Key key) {
        switch (key.pref) {
            case "assess":
            case "answer_in_menu":
            case "auto_captions":
                return true;
            case "mark_only":
            case "summary_panel":
            case "auto_cuts":
                return false;
            case "panel_delay_ms":
                return UtubotSettings.DEFAULT_PANEL_DELAY_MS;
            default:
                return UtubotSettings.DEFAULT_WAIT_MS;
        }
    }
}
