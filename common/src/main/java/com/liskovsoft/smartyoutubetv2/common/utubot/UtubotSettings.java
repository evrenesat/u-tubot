package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.SharedPreferences;

import com.liskovsoft.smartyoutubetv2.common.BuildConfig;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * The u-tubot settings, shared by every account. The backend address and token are empty until a setup is imported or the user
 * types them; private builds can bake defaults (-PutubotUrl, -PutubotToken).
 */
public class UtubotSettings {
    public static final int DEFAULT_WAIT_MS = 1200;
    public static final int MAX_WAIT_MS = 3000;
    public static final int NETWORK_SLACK_MS = 500;
    private static final String PREFS_NAME = "utubot_settings";
    private static final String KEY_URL = "url";
    private static final String KEY_TOKEN = "token";
    private static final String KEY_ASSESS = "assess";
    private static final String KEY_MARK_ONLY = "mark_only";
    private static final String KEY_ANSWER_IN_MENU = "answer_in_menu";
    private static final String KEY_PANEL = "summary_panel";
    private static final String KEY_AUTO_CAPTIONS = "auto_captions";
    private static final String KEY_WAIT_MS = "wait_ms";
    private static final String KEY_PAIR_PROMPT_DONE = "pair_prompt_done";
    private static final String KEY_SETUP_PROMPT_DONE = "setup_prompt_done";
    private static final String KEY_UPDATE_URL = "update_url";
    private static final String KEY_PENDING_PROMPT_SETS = "pending_prompt_sets";
    private static final String LIST_SEPARATOR = "\n";
    @SuppressLint("StaticFieldLeak")
    private static UtubotSettings sInstance;
    private final SharedPreferences mPrefs;
    private final List<Runnable> mPanelListeners = new CopyOnWriteArrayList<>();

    private UtubotSettings(Context context) {
        mPrefs = context.getApplicationContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public static synchronized UtubotSettings instance(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotSettings(context);
        }

        return sInstance;
    }

    /**
     * The flavor has the u-tubot layer built in (see the stutubot flavor)
     */
    public static boolean isBuiltIn() {
        return BuildConfig.UTUBOT_ENABLED;
    }

    public String getUrl() {
        return mPrefs.getString(KEY_URL, BuildConfig.UTUBOT_URL);
    }

    public void setUrl(String url) {
        mPrefs.edit().putString(KEY_URL, url != null ? url.trim() : "").apply();
    }

    /**
     * Where the update checker looks for new versions: the update_url of the imported setup. Empty means no update checks.
     */
    public String getUpdateUrl() {
        return mPrefs.getString(KEY_UPDATE_URL, "");
    }

    public void setUpdateUrl(String url) {
        mPrefs.edit().putString(KEY_UPDATE_URL, url != null ? url.trim() : "").apply();
    }

    /**
     * Stores what an imported setup says. The token of a previous backend is dropped when the backend address changes.
     */
    public void applySetup(UtubotSetup setup) {
        String previous = getUrl();

        if (!previous.equals(setup.backendUrl)) {
            setToken("");
            setPairPromptDone(false);
        }

        setUrl(setup.backendUrl);
        setUpdateUrl(setup.updateUrl);
        UtubotSetup.Defaults defaults = setup.defaults;

        if (defaults.assess != null) {
            setAssessEnabled(defaults.assess);
        }
        if (defaults.markOnly != null) {
            setMarkOnly(defaults.markOnly);
        }
        if (defaults.answerInMenu != null) {
            setAnswerInMenuEnabled(defaults.answerInMenu);
        }
        if (defaults.summaryPanel != null) {
            setSummaryPanelEnabled(defaults.summaryPanel);
        }
        if (defaults.autoCaptions != null) {
            setAutoCaptionsEnabled(defaults.autoCaptions);
        }

        mPrefs.edit().putString(KEY_PENDING_PROMPT_SETS, String.join(LIST_SEPARATOR, setup.promptSetUrls)).apply();
    }

    /**
     * Prompt set addresses from the setup, imported once the pairing gave a token
     */
    public List<String> takePendingPromptSets() {
        String stored = mPrefs.getString(KEY_PENDING_PROMPT_SETS, "");
        mPrefs.edit().remove(KEY_PENDING_PROMPT_SETS).apply();

        return stored.isEmpty() ? new ArrayList<>() : new ArrayList<>(java.util.Arrays.asList(stored.split(LIST_SEPARATOR)));
    }

    /**
     * The setup import dialog was offered once on the first launch (used or skipped)
     */
    public boolean isSetupPromptDone() {
        return mPrefs.getBoolean(KEY_SETUP_PROMPT_DONE, false);
    }

    public void setSetupPromptDone(boolean done) {
        mPrefs.edit().putBoolean(KEY_SETUP_PROMPT_DONE, done).apply();
    }

    public String getToken() {
        return mPrefs.getString(KEY_TOKEN, BuildConfig.UTUBOT_TOKEN);
    }

    public void setToken(String token) {
        mPrefs.edit().putString(KEY_TOKEN, token != null ? token.trim() : "").apply();
    }

    /**
     * Built in, and pointed at a backend
     */
    public boolean isConfigured() {
        return isBuiltIn() && !getUrl().isEmpty();
    }

    public boolean isAssessEnabled() {
        // Without a token every call is refused: nothing to assess before the pairing
        return isConfigured() && !getToken().isEmpty() && mPrefs.getBoolean(KEY_ASSESS, true);
    }

    public void setAssessEnabled(boolean enabled) {
        mPrefs.edit().putBoolean(KEY_ASSESS, enabled).apply();
    }

    public boolean isMarkOnly() {
        return mPrefs.getBoolean(KEY_MARK_ONLY, false);
    }

    public void setMarkOnly(boolean markOnly) {
        mPrefs.edit().putBoolean(KEY_MARK_ONLY, markOnly).apply();
    }

    public boolean isAnswerInMenuEnabled() {
        return isConfigured() && mPrefs.getBoolean(KEY_ANSWER_IN_MENU, true);
    }

    public void setAnswerInMenuEnabled(boolean enabled) {
        mPrefs.edit().putBoolean(KEY_ANSWER_IN_MENU, enabled).apply();
    }

    public boolean isSummaryPanelEnabled() {
        return isConfigured() && mPrefs.getBoolean(KEY_PANEL, false);
    }

    public void setSummaryPanelEnabled(boolean enabled) {
        mPrefs.edit().putBoolean(KEY_PANEL, enabled).apply();

        for (Runnable listener : new ArrayList<>(mPanelListeners)) {
            listener.run();
        }
    }

    /**
     * Called when the panel mode is switched. Held strongly: remove it when the view goes away.
     */
    public void addPanelListener(Runnable listener) {
        mPanelListeners.add(listener);
    }

    public void removePanelListener(Runnable listener) {
        mPanelListeners.remove(listener);
    }

    public boolean isAutoCaptionsEnabled() {
        return mPrefs.getBoolean(KEY_AUTO_CAPTIONS, true);
    }

    public void setAutoCaptionsEnabled(boolean enabled) {
        mPrefs.edit().putBoolean(KEY_AUTO_CAPTIONS, enabled).apply();
    }

    /**
     * The pairing dialog was shown (and closed or used) once: it doesn't open by itself again
     */
    public boolean isPairPromptDone() {
        return mPrefs.getBoolean(KEY_PAIR_PROMPT_DONE, false);
    }

    public void setPairPromptDone(boolean done) {
        mPrefs.edit().putBoolean(KEY_PAIR_PROMPT_DONE, done).apply();
    }

    public int getWaitMs() {
        return Math.min(mPrefs.getInt(KEY_WAIT_MS, DEFAULT_WAIT_MS), MAX_WAIT_MS);
    }

    public void setWaitMs(int waitMs) {
        mPrefs.edit().putInt(KEY_WAIT_MS, Math.max(0, Math.min(waitMs, MAX_WAIT_MS))).apply();
    }
}
