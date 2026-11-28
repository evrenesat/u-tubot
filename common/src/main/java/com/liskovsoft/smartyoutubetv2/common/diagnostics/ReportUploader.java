package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import android.annotation.SuppressLint;
import android.content.Context;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import androidx.annotation.Nullable;
import androidx.annotation.VisibleForTesting;

import com.liskovsoft.sharedutils.helpers.AppInfoHelpers;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.DebuggingData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotClient;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPlayerLog;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.GZIPOutputStream;

import com.liskovsoft.smartyoutubetv2.common.BuildConfig;

/**
 * Sends the crash reports (the player failure log's new entries) and the player event files to the u-tubot backend: gzip, redacted on
 * the TV first, only while nothing plays, a while after the app starts, after playback ends and every {@link #PERIOD_MS}. A failed
 * try is repeated after a doubling wait. What the server confirmed is dropped from the TV, the rest stays.
 */
public final class ReportUploader {
    public static final long START_DELAY_MS = 60_000;
    public static final long PERIOD_MS = 6 * 3_600_000L;
    public static final long IDLE_RECHECK_MS = 2 * 60_000;
    public static final long AFTER_PLAYBACK_MS = 30_000;
    public static final long BACKOFF_START_MS = 60_000;
    public static final long BACKOFF_MAX_MS = 3_600_000;
    static final int REQUEST_TIMEOUT_MS = 30_000;
    /**
     * Of the report as text: the server refuses more (`[reports] max_report_bytes`)
     */
    static final int MAX_REPORT_CHARS = 1_500_000;
    private static final int SCHEMA = 1;
    @SuppressLint("StaticFieldLeak")
    private static ReportUploader sInstance;
    private final Context mContext;
    private final Handler mMain = new Handler(Looper.getMainLooper());
    private final ExecutorService mNetwork = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "utubot-report-upload");
        thread.setDaemon(true);
        thread.setPriority(Thread.MIN_PRIORITY);
        return thread;
    });
    private final AtomicBoolean mIsRunning = new AtomicBoolean();
    private final Runnable mTick = this::tick;
    private long mBackoffMs = BACKOFF_START_MS;

    private ReportUploader(Context context) {
        mContext = context.getApplicationContext();
    }

    public static synchronized void start(Context context) {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        if (sInstance == null) {
            sInstance = new ReportUploader(context);
            sInstance.schedule(START_DELAY_MS);
        }
    }

    /**
     * Playback ended or the player closed: a quiet moment to send
     */
    public static synchronized void onPlaybackEnded() {
        if (sInstance != null) {
            sInstance.schedule(AFTER_PLAYBACK_MS);
        }
    }

    private void schedule(long delayMs) {
        mMain.removeCallbacks(mTick);
        mMain.postDelayed(mTick, delayMs);
    }

    private void tick() {
        if (isPlaying()) {
            schedule(IDLE_RECHECK_MS);
            return;
        }

        if (!mIsRunning.compareAndSet(false, true)) {
            return;
        }

        mNetwork.execute(() -> {
            long next;

            try {
                next = upload() ? PERIOD_MS : nextBackoff();
            } catch (RuntimeException e) {
                next = nextBackoff();
            } finally {
                mIsRunning.set(false);
            }

            schedule(next);
        });
    }

    private long nextBackoff() {
        long wait = mBackoffMs;
        mBackoffMs = Math.min(mBackoffMs * 2, BACKOFF_MAX_MS);

        return wait;
    }

    private boolean isPlaying() {
        try {
            return PlaybackPresenter.instance(mContext).isPlaying();
        } catch (RuntimeException e) {
            return false;
        }
    }

    /**
     * @return false to try again after a wait: the server or the network failed
     */
    private boolean upload() {
        UtubotSettings settings = UtubotSettings.instance(mContext);

        if (!settings.isConfigured() || settings.getToken().isEmpty()) {
            return true; // nothing to send to: the next period looks again
        }

        DataSubmitter.Unsent unsent = DataSubmitter.Unsent.read(mContext);
        List<File> files = UtubotPlayerLog.filesForUpload();

        if (unsent.failures.isEmpty() && files.isEmpty()) {
            mBackoffMs = BACKOFF_START_MS;
            return true;
        }

        try {
            JSONObject report = build(mContext, unsent.failures, readLines(files), secretsOf(settings));
            byte[] body = gzip(report.toString());
            String answer = new UtubotClient(settings.getUrl(), settings.getToken()).quiet().postDeviceReport(body, REQUEST_TIMEOUT_MS);
            String id = new JSONObject(answer).optString("id", "");

            if (id.isEmpty()) {
                return false;
            }

            DebuggingData.instance(mContext).setLastSubmission(id, unsent.newestFailureTs, unsent.newestStartTs, System.currentTimeMillis());
            UtubotPlayerLog.deleteUploaded(files);
            mBackoffMs = BACKOFF_START_MS;

            return true;
        } catch (IOException | JSONException e) {
            return false;
        }
    }

    private static String[] secretsOf(UtubotSettings settings) {
        return new String[]{settings.getToken(), settings.getFilmsRealDebridToken(), settings.getFilmsAddonUrl()};
    }

    private static List<String> readLines(List<File> files) {
        List<String> lines = new ArrayList<>();

        for (File file : files) {
            try {
                for (String line : new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8).split("\n")) {
                    if (!line.isEmpty()) {
                        lines.add(line);
                    }
                }
            } catch (IOException e) {
                // Left on the disk, not sent
            }
        }

        return lines;
    }

    /**
     * The report as the server stores it: app, device, the failures and the events, all redacted with the secrets of this TV. Over
     * the size the server takes, the oldest events go first, then the oldest failures.
     */
    public static JSONObject build(Context context, List<JSONObject> failures, List<String> events, String... secrets) {
        JSONObject app = new JSONObject();
        JSONObject device = new JSONObject();

        try {
            app.put("version", AppInfoHelpers.getAppVersionName(context));
            app.put("code", AppInfoHelpers.getAppVersionCode(context));
            app.put("flavor", BuildConfig.FLAVOR);
            device.put("model", Build.MANUFACTURER + " " + Build.MODEL);
            device.put("sdk", Build.VERSION.SDK_INT);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return assemble(app, device, failures, events, secrets);
    }

    @VisibleForTesting
    static JSONObject assemble(JSONObject app, JSONObject device, List<JSONObject> failures, List<String> events, String... secrets) {
        List<JSONObject> safeFailures = new ArrayList<>();
        List<String> safeEvents = new ArrayList<>();
        int chars = 0;

        for (int i = failures.size() - 1; i >= 0; i--) {
            JSONObject failure = redactFailure(failures.get(i), secrets);
            int length = failure.toString().length();

            if (chars + length > MAX_REPORT_CHARS / 2) {
                break;
            }

            chars += length;
            safeFailures.add(0, failure);
        }

        for (int i = events.size() - 1; i >= 0; i--) {
            String line = Scrubber.scrub(ReportRedaction.redact(events.get(i), secrets));

            if (chars + line.length() + 4 > MAX_REPORT_CHARS) {
                break;
            }

            chars += line.length() + 4;
            safeEvents.add(0, line);
        }

        JSONObject report = new JSONObject();

        try {
            report.put("schema", SCHEMA);
            report.put("app", app);
            report.put("device", device);
            report.put("failures", new JSONArray(safeFailures));
            report.put("events", new JSONArray(safeEvents));
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }

        return report;
    }

    private static JSONObject redactFailure(JSONObject failure, String... secrets) {
        String text = Scrubber.scrub(ReportRedaction.redact(failure.toString(), secrets));

        try {
            return new JSONObject(text);
        } catch (JSONException e) {
            JSONObject stub = new JSONObject();

            try {
                stub.put("kind", failure.optString("kind", "unknown"));
                stub.put("ts", failure.optLong("ts"));
                stub.put("note", "unreadable after redaction");
            } catch (JSONException ignored) {
                // Cannot happen for plain values
            }

            return stub;
        }
    }

    @Nullable
    static byte[] gzipOrNull(String text) {
        try {
            return gzip(text);
        } catch (IOException e) {
            return null;
        }
    }

    static byte[] gzip(String text) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();

        try (GZIPOutputStream out = new GZIPOutputStream(bytes)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }

        return bytes.toByteArray();
    }
}
