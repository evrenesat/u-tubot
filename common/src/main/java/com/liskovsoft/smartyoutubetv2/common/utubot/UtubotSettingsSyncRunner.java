package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import com.liskovsoft.sharedutils.helpers.AppInfoHelpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import org.json.JSONObject;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Runs {@link UtubotSettingsSync} in the app: a round at start, when a settings screen opens or the app comes back to the front,
 * shortly after a local change and every {@link #POLL_MS} while the app is in front. A failed round is tried again after a
 * growing wait. The network runs on its own thread; the main thread only schedules.
 */
public final class UtubotSettingsSyncRunner {
    public static final long POLL_MS = 30_000;
    public static final long BACKOFF_MAX_MS = 600_000;
    public static final long START_DELAY_MS = 3_000;
    public static final long CHANGE_DELAY_MS = 500;
    /** How long the server may hold the "anything new?" request; a change on the web reaches the TV the moment it is saved */
    public static final int WATCH_WAIT_MS = 20_000;
    private static final String STATE_PREFS = "utubot_settings_sync";
    private static final String COPY_PREFS = "utubot_settings_pre_sync";
    @SuppressLint("StaticFieldLeak")
    private static UtubotSettingsSyncRunner sInstance;
    private final Context mContext;
    private final UtubotSettings mSettings;
    private final UtubotSettingsSync mSync;
    private final Handler mMain = new Handler(Looper.getMainLooper());
    private final ExecutorService mNetwork = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "utubot-settings-sync");
        thread.setDaemon(true);
        return thread;
    });
    private final ExecutorService mWatcher = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "utubot-settings-watch");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicBoolean mIsRunning = new AtomicBoolean();
    private final AtomicBoolean mIsWatching = new AtomicBoolean();
    private final Runnable mTick = this::tick;
    private long mBackoffMs = POLL_MS;

    private UtubotSettingsSyncRunner(Context context) {
        mContext = context.getApplicationContext();
        mSettings = UtubotSettings.instance(mContext);
        SharedPreferences state = mContext.getSharedPreferences(STATE_PREFS, Context.MODE_PRIVATE);
        SharedPreferences copy = mContext.getSharedPreferences(COPY_PREFS, Context.MODE_PRIVATE);
        mSync = new UtubotSettingsSync(mSettings, state, copy, new UtubotSettingsSync.Transport() {
            @Override
            public String get(int have, int schemaVersion, int waitMs) throws IOException {
                return client().deviceSettings(have, schemaVersion, waitMs, UtubotSettingsSync.REQUEST_TIMEOUT_MS);
            }

            @Override
            public String post(JSONObject body) throws IOException {
                return client().postDeviceSettings(body, UtubotSettingsSync.REQUEST_TIMEOUT_MS);
            }
        }, System::currentTimeMillis, AppInfoHelpers.getAppVersionName(mContext));
        mSettings.setChangeListener(pref -> {
            mSync.onLocalChange(pref);
            requestSoon(CHANGE_DELAY_MS);
        });
        mSettings.addConnectionListener(() -> {
            mSync.onConnectionChanged();
            requestSoon(CHANGE_DELAY_MS);
        });
    }

    private UtubotClient client() {
        return new UtubotClient(mSettings.getUrl(), mSettings.getToken()).quiet();
    }

    /**
     * Starts the sync once. Nothing in the other flavors.
     */
    public static synchronized void start(Context context) {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        if (sInstance == null) {
            sInstance = new UtubotSettingsSyncRunner(context);
            sInstance.requestSoon(START_DELAY_MS);
        }
    }

    /**
     * A settings screen opened or the app came back to the front: look at the server now
     */
    public static synchronized void requestNow(Context context) {
        if (sInstance != null) {
            sInstance.requestSoon(0);
        }
    }

    public static synchronized UtubotSettingsSync.Status status() {
        return sInstance != null ? sInstance.mSync.getStatus() : UtubotSettingsSync.Status.NOT_PAIRED;
    }

    public static synchronized long lastOkMs() {
        return sInstance != null ? sInstance.mSync.getLastOkMs() : 0;
    }

    private void requestSoon(long delayMs) {
        mMain.removeCallbacks(mTick);
        mMain.postDelayed(mTick, delayMs);
    }

    private void tick() {
        if (!Utils.isAppInForegroundFixed()) {
            mMain.postDelayed(mTick, POLL_MS);
            return;
        }

        if (!mIsRunning.compareAndSet(false, true)) {
            mMain.postDelayed(mTick, CHANGE_DELAY_MS);
            return;
        }

        mNetwork.execute(() -> {
            UtubotSettingsSync.Status status = mSync.syncOnce();
            mIsRunning.set(false);
            mMain.post(() -> afterRound(status));
        });
    }

    private void afterRound(UtubotSettingsSync.Status status) {
        showSuperseded(mSync.takeSuperseded());
        mMain.removeCallbacks(mTick);

        if (status == UtubotSettingsSync.Status.FAILED) {
            mMain.postDelayed(mTick, mBackoffMs);
            mBackoffMs = Math.min(mBackoffMs * 2, BACKOFF_MAX_MS);
            return;
        }

        mBackoffMs = POLL_MS;

        if (status == UtubotSettingsSync.Status.SYNCED) {
            armWatch();
        }

        // The sync stays quiet when the server has no web settings: it looks again only after a restart or a new connection
        mMain.postDelayed(mTick, status == UtubotSettingsSync.Status.OFF ? BACKOFF_MAX_MS : POLL_MS);
    }

    /**
     * Keeps one "anything new?" request open at the server while the app is in front. It answers the moment the web saves a
     * change; the timer stays as the fallback (a server that does not hold requests, a failed request).
     */
    private void armWatch() {
        if (!Utils.isAppInForegroundFixed() || !mIsWatching.compareAndSet(false, true)) {
            return;
        }

        mWatcher.execute(() -> {
            UtubotSettingsSync.Watch result = mSync.watch(WATCH_WAIT_MS);
            mIsWatching.set(false);
            mMain.post(() -> afterWatch(result));
        });
    }

    private void afterWatch(UtubotSettingsSync.Watch result) {
        if (result == UtubotSettingsSync.Watch.CHANGED) {
            requestSoon(0);
        } else if (result == UtubotSettingsSync.Watch.HELD) {
            armWatch();
        }
    }

    private void showSuperseded(List<String> keys) {
        for (String key : keys) {
            int title = titleOf(key);

            if (title != 0) {
                MessageHelpers.showLongMessage(mContext, mContext.getString(R.string.utubot_sync_superseded, mContext.getString(title)));
            }
        }
    }

    static int titleOf(String key) {
        switch (key) {
            case "ai.assess":
                return R.string.utubot_assess;
            case "ai.mark_only":
                return R.string.utubot_mark_only;
            case "ai.answer_in_menu":
                return R.string.utubot_answer_in_menu;
            case "ai.summary_panel":
                return R.string.utubot_summary_panel;
            case "ai.panel_delay_ms":
                return R.string.utubot_panel_delay;
            case "ai.auto_captions":
                return R.string.utubot_auto_captions;
            case "ai.auto_cuts":
                return R.string.utubot_auto_cuts;
            case "updates.checks":
                return R.string.utubot_update_checks;
            case "ai.auto_scroll_speed":
                return R.string.utubot_auto_scroll;
            case "ai.cut_jump":
                return R.string.utubot_cut_jump;
            case "updates.interval_minutes":
                return R.string.utubot_update_interval;
            case "updates.development_mode":
                return R.string.utubot_development_mode;
            case "browse.refresh_minutes":
                return R.string.utubot_browse_refresh;
            default:
                return 0;
        }
    }
}
