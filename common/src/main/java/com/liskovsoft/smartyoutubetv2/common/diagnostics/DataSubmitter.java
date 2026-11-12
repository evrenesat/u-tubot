package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import android.content.Context;
import android.text.TextUtils;

import androidx.annotation.Nullable;
import androidx.annotation.VisibleForTesting;

import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.okhttp.OkHttpManager;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.prefs.DebuggingData;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.GZIPOutputStream;

import io.reactivex.Observable;
import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

/**
 * Sends the {@link DiagnosticsReport} to the diagnostics server, gzipped, with the app's own network settings (DNS, IPv6, proxy)
 */
public final class DataSubmitter {
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");

    /**
     * Refused by the server: why, e.g. "HTTP 413"
     */
    public static final class SubmitException extends IOException {
        public final int code;

        SubmitException(int code, String message) {
            super(message);
            this.code = code;
        }
    }

    /**
     * The player failures and the video starts recorded since the last submission: the ones sent before stay in the logs, but
     * aren't sent again
     */
    public static final class Unsent {
        /**
         * Oldest first
         */
        public final List<JSONObject> failures;
        public final List<JSONObject> videoStarts;
        /**
         * Of the newest of each, the last submission's when none is newer: where the next submission starts from
         */
        final long newestFailureTs;
        final long newestStartTs;

        private Unsent(List<JSONObject> failures, List<JSONObject> videoStarts, long newestFailureTs, long newestStartTs) {
            this.failures = failures;
            this.videoStarts = videoStarts;
            this.newestFailureTs = newestFailureTs;
            this.newestStartTs = newestStartTs;
        }

        /**
         * Blocks till the logs are read: not on the main thread
         */
        public static Unsent read(Context context) {
            DebuggingData debuggingData = DebuggingData.instance(context);

            return read(PlayerFailureLog.instance(context).readAll(), debuggingData.getLastSubmittedFailureTs(),
                    VideoStartLog.instance(context).readAll(), debuggingData.getLastSubmittedStartTs(), System.currentTimeMillis());
        }

        @VisibleForTesting
        static Unsent read(List<JSONObject> allFailures, long lastFailureTs, List<JSONObject> allStarts, long lastStartTs, long nowMs) {
            List<JSONObject> failures = new ArrayList<>();
            List<JSONObject> starts = new ArrayList<>();

            return new Unsent(failures, starts, after(allFailures, lastFailureTs, nowMs, failures),
                    after(allStarts, lastStartTs, nowMs, starts));
        }

        /**
         * The ones newer than the last submission's newest. A clock set back since then (it was ahead) would hold back every
         * one after it till it caught up: they're all sent again instead.
         *
         * @return the time of the newest
         */
        private static long after(List<JSONObject> all, long lastTs, long nowMs, List<JSONObject> result) {
            long cutoff = lastTs > nowMs ? 0 : lastTs;
            long newest = cutoff;

            for (JSONObject item : all) {
                long ts = item.optLong("ts");

                if (ts > cutoff) {
                    result.add(item);
                    newest = Math.max(newest, ts);
                }
            }

            return newest;
        }
    }

    private static final String TAG = DataSubmitter.class.getSimpleName();

    private DataSubmitter() {
    }

    /**
     * Built and sent in the background. Emits the submission's ID.
     */
    public static Observable<String> submitObserve(Context context) {
        Context appContext = context.getApplicationContext();

        return RxHelper.fromCallable(() -> submit(appContext, false));
    }

    /**
     * What would be sent now, readable (see the Debugging panel's Preview data)
     */
    public static Observable<String> previewObserve(Context context) {
        Context appContext = context.getApplicationContext();

        return RxHelper.fromCallable(() -> {
            Unsent unsent = Unsent.read(appContext);
            JSONObject report = DiagnosticsReport.build(appContext, unsent.failures, unsent.videoStarts);
            return report.toString(1);
        });
    }

    /**
     * A flavor without the address of a server (submit_data_url) has no submitting: Settings → Debugging doesn't offer it
     */
    public static boolean isConfigured(Context context) {
        return !TextUtils.isEmpty(context.getString(R.string.submit_data_url));
    }

    /**
     * When the app starts, with Settings → Debugging → Submit data on startup on (see AutoSubmitWorker). Turned off: nothing's
     * scheduled anymore.
     */
    public static void autoSubmit(Context context) {
        if (!isConfigured(context)) {
            return;
        }

        try {
            AutoSubmitWorker.schedule(context.getApplicationContext());
        } catch (RuntimeException e) {
            Log.e(TAG, "Can't schedule the submission: " + e.getMessage());
        }
    }

    /**
     * One at a time: the startup and the daily submissions (see AutoSubmitWorker) can run together, and the second is to see
     * what the first sent
     *
     * @param onlyIfNew nothing is sent, and null returned, when no failure was recorded since the last submission
     */
    @Nullable
    static synchronized String submit(Context context, boolean onlyIfNew) throws IOException {
        Unsent unsent = Unsent.read(context);

        // Not the unsent ones: with the clock set back since the last submission they're all of them, every time
        if (onlyIfNew && unsent.newestFailureTs <= DebuggingData.instance(context).getLastSubmittedFailureTs()) {
            return null;
        }

        String id = submit(context.getString(R.string.submit_data_url),
                DiagnosticsReport.build(context, unsent.failures, unsent.videoStarts));
        DebuggingData.instance(context).setLastSubmission(id, unsent.newestFailureTs, unsent.newestStartTs, System.currentTimeMillis());

        return id;
    }

    static String submit(String url, JSONObject report) throws IOException {
        Request request = new Request.Builder()
                .url(url)
                .header("Content-Encoding", "gzip")
                .post(RequestBody.create(gzip(report.toString()), JSON))
                .build();

        try (Response response = OkHttpManager.instance().getClient().newCall(request).execute()) {
            ResponseBody body = response.body();
            String text = body != null ? body.string() : "";

            if (!response.isSuccessful()) {
                throw new SubmitException(response.code(), "HTTP " + response.code() + errorOf(text));
            }

            String id = new JSONObject(text).optString("id", "");

            if (id.isEmpty()) {
                throw new IOException("No ID in the response");
            }

            return id;
        } catch (JSONException e) {
            throw new IOException("Invalid response", e);
        }
    }

    private static String errorOf(String responseText) {
        try {
            String error = new JSONObject(responseText).optString("error", "");
            return error.isEmpty() ? "" : ": " + error;
        } catch (JSONException e) {
            return "";
        }
    }

    static byte[] gzip(String text) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();

        try (GZIPOutputStream gzip = new GZIPOutputStream(bytes)) {
            gzip.write(text.getBytes(StandardCharsets.UTF_8));
        }

        return bytes.toByteArray();
    }
}
