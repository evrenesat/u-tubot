package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import android.app.ActivityManager;
import android.app.ActivityManager.RunningAppProcessInfo;
import android.app.ApplicationExitInfo;
import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.prefs.DebuggingData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;

import org.json.JSONObject;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowActivityManager.ApplicationExitInfoBuilder;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class AppExitsTest {
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private PlayerFailureLog mLog;
    private int mSavedEngine;
    private long mSavedLastExitTs;

    @Before
    public void setUp() {
        mLog = PlayerFailureLog.useForTesting(mFolder.getRoot());
        FormatAttempts.resetForTesting();
        // Cronet can't load under Robolectric
        mSavedEngine = PlayerTweaksData.instance(getContext()).getPlayerDataSource();
        // The exits seen are kept between the tests: each sees its own
        mSavedLastExitTs = DebuggingData.instance(getContext()).getLastAppExitTs();
        DebuggingData.instance(getContext()).setLastAppExitTs(0);
        PlayerTweaksData.instance(getContext()).setPlayerDataSource(PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP);
    }

    @After
    public void tearDown() {
        LastState.resetForTesting(getContext());
        FormatAttempts.resetForTesting();
        PlayerFailureLog.useForTesting(null);
        PlayerTweaksData.instance(getContext()).setPlayerDataSource(mSavedEngine);
        DebuggingData.instance(getContext()).setLastAppExitTs(mSavedLastExitTs);
    }

    /**
     * On the disk before the handler returns (the app dies next), with the video playing
     */
    /**
     * The crash report holds the last events of the player log and the log is on the disk too
     */
    @Test
    public void aCrashCarriesTheRecentPlayerEventsAndFlushesThem() throws Exception {
        com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog.useForTesting(
                com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog.createForTesting(mFolder.newFolder("events"), 16, 4096, 2));

        try {
            com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog.event("player.open", "film");

            AppExits.recordCrash(getContext(), new Thread("main"), new IllegalStateException("Boom"));

            String written = new String(Files.readAllBytes(new File(mFolder.getRoot(), PlayerFailureLog.CURRENT).toPath()), StandardCharsets.UTF_8);
            assertTrue(written, written.contains("recentEvents"));
            assertTrue(written, written.contains("player.open film"));
            List<File> files = com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog.filesForUpload();
            assertEquals(1, files.size());
            assertTrue(new String(Files.readAllBytes(files.get(0).toPath()), StandardCharsets.UTF_8).contains("crash IllegalStateException: Boom"));
        } finally {
            com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog.useForTesting(null);
        }
    }

    @Test
    public void aCrashIsWrittenRightAway() throws Exception {
        FormatAttempts.onNewVideo(getContext(), "playing");

        AppExits.recordCrash(getContext(), new Thread("worker"), new IllegalStateException("Boom"));

        String written = new String(Files.readAllBytes(new File(mFolder.getRoot(), PlayerFailureLog.CURRENT).toPath()), StandardCharsets.UTF_8);
        assertTrue(written, written.contains("\"kind\":\"crash\""));
        assertTrue(written, written.contains("\"videoId\":\"playing\""));
        assertTrue(written, written.contains("\"thread\":\"worker\""));
        assertTrue(written, written.contains("Boom"));
    }

    @Test
    public void noExitsBeforeAndroid11() {
        // Robolectric runs as Android 9: nothing read, nothing thrown
        AppExits.recordNew(getContext());
    }

    /**
     * Killed in the background, e.g. by the low memory killer of a device that doesn't report its kills: how important the
     * process was, the signal, and whether the device reports them
     */
    @Test
    @Config(sdk = 30)
    public void aSignaledExitHasItsImportanceAndSignal() throws Exception {
        ActivityManager activityManager = (ActivityManager) getContext().getSystemService(Context.ACTIVITY_SERVICE);
        shadowOf(activityManager).addApplicationExitInfo(ApplicationExitInfoBuilder.newBuilder()
                .setTimestamp(System.currentTimeMillis())
                .setReason(ApplicationExitInfo.REASON_SIGNALED)
                .setStatus(9)
                .setImportance(RunningAppProcessInfo.IMPORTANCE_SERVICE)
                .setProcessName(getContext().getPackageName())
                .build());

        AppExits.recordNew(getContext());

        JSONObject details = mLog.readAll().get(0).getJSONObject("details");
        assertEquals("signaled", details.getString("reason"));
        assertFalse(details.getBoolean("foreground"));
        assertEquals(RunningAppProcessInfo.IMPORTANCE_SERVICE, details.getInt("importance"));
        assertEquals(9, details.getInt("status"));
        assertEquals(ActivityManager.isLowMemoryKillReportSupported(), details.getBoolean("lowMemoryKillReport"));
    }

    /**
     * The WebView's process, killed with the app's: one exit
     */
    @Test
    @Config(sdk = 30)
    public void aSandboxedProcessThatWentWithTheAppIsNotRecordedToo() throws Exception {
        long now = System.currentTimeMillis() - 120_000;
        addExit("com.google.android.webview:sandboxed_process0:org.chromium.content.app.SandboxedProcessService0:0", now);
        addExit(getContext().getPackageName(), now + 25);

        AppExits.recordNew(getContext());

        List<JSONObject> events = mLog.readAll();
        assertEquals(1, events.size());
        assertEquals(getContext().getPackageName(), events.get(0).getJSONObject("details").getString("process"));
    }

    /**
     * Alone, the WebView's renderer failed
     */
    @Test
    @Config(sdk = 30)
    public void aSandboxedProcessThatWentAloneIsRecorded() throws Exception {
        long now = System.currentTimeMillis() - 120_000;
        String sandbox = "com.google.android.webview:sandboxed_process0:org.chromium.content.app.SandboxedProcessService0:0";
        addExit(sandbox, now);
        addExit(getContext().getPackageName(), now + 60_000);

        AppExits.recordNew(getContext());

        List<JSONObject> events = mLog.readAll();
        assertEquals(2, events.size());
        assertEquals(sandbox, events.get(0).getJSONObject("details").getString("process"));
    }

    private void addExit(String process, long timestamp) {
        ActivityManager activityManager = (ActivityManager) getContext().getSystemService(Context.ACTIVITY_SERVICE);
        shadowOf(activityManager).addApplicationExitInfo(ApplicationExitInfoBuilder.newBuilder()
                .setTimestamp(timestamp)
                .setReason(ApplicationExitInfo.REASON_SIGNALED)
                .setStatus(9)
                .setImportance(RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE)
                .setProcessName(process)
                .build());
    }

    /**
     * Android closing it to make room: not a failure
     */
    @Test
    @Config(sdk = 30)
    public void aCachedAppKilledIsNotRecorded() throws Exception {
        ActivityManager activityManager = (ActivityManager) getContext().getSystemService(Context.ACTIVITY_SERVICE);
        shadowOf(activityManager).addApplicationExitInfo(ApplicationExitInfoBuilder.newBuilder()
                .setTimestamp(System.currentTimeMillis())
                .setReason(ApplicationExitInfo.REASON_SIGNALED)
                .setStatus(9)
                .setImportance(RunningAppProcessInfo.IMPORTANCE_CACHED)
                .setProcessName(getContext().getPackageName())
                .build());

        AppExits.recordNew(getContext());

        assertTrue(mLog.readAll().isEmpty());
    }

    /**
     * Where the low memory killer reports its kills, they're low_memory ones: of a cached app, the same as a signaled one
     */
    @Test
    @Config(sdk = 30)
    public void aCachedAppTheLowMemoryKillerKilledIsNotRecorded() throws Exception {
        ActivityManager activityManager = (ActivityManager) getContext().getSystemService(Context.ACTIVITY_SERVICE);
        shadowOf(activityManager).addApplicationExitInfo(ApplicationExitInfoBuilder.newBuilder()
                .setTimestamp(System.currentTimeMillis())
                .setReason(ApplicationExitInfo.REASON_LOW_MEMORY)
                .setImportance(RunningAppProcessInfo.IMPORTANCE_CACHED)
                .setProcessName(getContext().getPackageName())
                .build());

        AppExits.recordNew(getContext());

        assertTrue(mLog.readAll().isEmpty());
    }

    /**
     * Killed for memory while it was used (e.g. playing in the background): a failure
     */
    @Test
    @Config(sdk = 30)
    public void aLowMemoryKillWhileUsedIsRecorded() throws Exception {
        ActivityManager activityManager = (ActivityManager) getContext().getSystemService(Context.ACTIVITY_SERVICE);
        shadowOf(activityManager).addApplicationExitInfo(ApplicationExitInfoBuilder.newBuilder()
                .setTimestamp(System.currentTimeMillis())
                .setReason(ApplicationExitInfo.REASON_LOW_MEMORY)
                .setImportance(RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE)
                .setProcessName(getContext().getPackageName())
                .build());

        AppExits.recordNew(getContext());

        assertEquals("low_memory", mLog.readAll().get(0).getJSONObject("details").getString("reason"));
    }

    /**
     * Killed while the remote control's service ran: what it was doing comes with it, Android doesn't say
     */
    @Test
    @Config(sdk = 30)
    public void anExitHasWhatItsProcessWasDoing() throws Exception {
        long now = System.currentTimeMillis();
        LastState.sPid = () -> 4242;
        LastState.sWallClock = () -> now - 5_000;
        LastState.onServiceStarted(getContext(), LastState.SERVICE_REMOTE_CONTROL);
        ActivityManager activityManager = (ActivityManager) getContext().getSystemService(Context.ACTIVITY_SERVICE);
        shadowOf(activityManager).addApplicationExitInfo(ApplicationExitInfoBuilder.newBuilder()
                .setTimestamp(now)
                .setPid(4242)
                .setReason(ApplicationExitInfo.REASON_SIGNALED)
                .setStatus(9)
                .setImportance(RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE)
                .setProcessName(getContext().getPackageName())
                .build());

        AppExits.recordNew(getContext());

        JSONObject lastState = mLog.readAll().get(0).getJSONObject("details").getJSONObject("lastState");
        assertEquals(LastState.SERVICE_REMOTE_CONTROL, lastState.getJSONArray("services").getString(0));
        assertEquals(5_000, lastState.getLong("agoMs"));
    }

    private static Context getContext() {
        return RuntimeEnvironment.getApplication();
    }
}
