package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Flag;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The verdicts and summaries of earlier sessions, kept on the TV so a restart does not ask the backend again. Only ready answers are
 * stored: a failure, a pending job or a transcript state is never kept (see "Failure policy" in ai/CONTRACT.md), so a failure cannot
 * outlive the session it happened in.
 * <p>
 * Everything lives in one scope, the hash of the backend address, the token and the backend's data schema: another backend, another user or a
 * change of the shape of the cached data starts empty (a deploy that keeps the shape keeps the cache, so the TV works offline), and the directories of other scopes are removed. An
 * entry also expires after {@link #TTL_MS}, because a change of the backend's model or settings does not change the schema. Layout:
 * {@code <root>/<scope>/verdicts.json} and {@code <root>/<scope>/summaries/<video id>-<prompt hash>.json}. A damaged file is dropped.
 */
public class UtubotDiskCache {
    public static final String DIRECTORY = "utubot_cache";
    public static final long TTL_MS = 3L * 24 * 60 * 60 * 1000;
    public static final int MAX_VERDICTS = VerdictCache.MAX_ENTRIES;
    public static final int MAX_SUMMARIES = 300;
    public static final int MAX_CUTS = 200;
    private static final String VERDICTS_FILE = "verdicts.json";
    private static final String SUMMARIES_DIRECTORY = "summaries";
    private static final String CUTS_DIRECTORY = "cuts";
    private static final String TEMP_EXTENSION = ".tmp";
    private static final int MAX_FILE_BYTES = 8 * 1024 * 1024;
    private static final int CHUNK_BYTES = 4096;
    private static final int SCOPE_LENGTH = 16;
    private static final int PROMPT_HASH_LENGTH = 8;
    private static final String TAG = UtubotDiskCache.class.getSimpleName();
    @SuppressLint("StaticFieldLeak")
    private static UtubotDiskCache sInstance;

    /** What time it is, so a test can age the entries */
    public interface Clock {
        long now();
    }

    /**
     * A stored cut list with the video it is for and the ETag it was cached under, so the caller can
     * re-validate it next time
     */
    public static final class CutListCache {
        public final UtubotModels.CutList cuts;
        public final String videoId;
        public final String etag;

        public CutListCache(UtubotModels.CutList cuts, String videoId, String etag) {
            this.cuts = cuts;
            this.videoId = videoId;
            this.etag = etag;
        }
    }

    private final File mRoot;
    private final Clock mClock;
    private String mScope;
    /** The stored verdicts of the scope with the time each was stored, the oldest first. Null until read. */
    private Map<String, Long> mVerdictTimes;
    private Map<String, Verdict> mVerdicts;

    public UtubotDiskCache(File root, Clock clock) {
        mRoot = root;
        mClock = clock;
    }

    public static synchronized UtubotDiskCache instance(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotDiskCache(new File(context.getApplicationContext().getFilesDir(), DIRECTORY), System::currentTimeMillis);
        }

        return sInstance;
    }

    /**
     * The scope of an answer: the same backend, user and cache data schema (never the build version)
     */
    public static String scopeOf(String baseUrl, String token, String cacheSchema) {
        return sha256(baseUrl + "\n" + token + "\n" + cacheSchema).substring(0, SCOPE_LENGTH);
    }

    /**
     * Makes the scope the one the next calls work in. The directories of every other scope are removed.
     */
    public synchronized void useScope(String scope) {
        if (scope.equals(mScope)) {
            return;
        }

        mScope = scope;
        mVerdictTimes = null;
        mVerdicts = null;
        File[] others = mRoot.listFiles();

        if (others == null) {
            return;
        }

        for (File other : others) {
            if (!other.getName().equals(scope)) {
                deleteRecursively(other);
            }
        }
    }

    //region Verdicts

    /**
     * The stored verdicts that have not expired, newest last
     */
    public synchronized List<Verdict> loadVerdicts() {
        readVerdicts();
        return new ArrayList<>(mVerdicts.values());
    }

    /**
     * Stores the ready verdicts; the oldest are dropped beyond {@link #MAX_VERDICTS}
     */
    public synchronized void putVerdicts(List<Verdict> verdicts) {
        if (mScope == null) {
            return;
        }

        readVerdicts();
        boolean isChanged = false;

        for (Verdict verdict : verdicts) {
            if (verdict != null && verdict.videoId != null && verdict.isReady()) {
                // Put at the end: the newest last
                mVerdicts.remove(verdict.videoId);
                mVerdictTimes.remove(verdict.videoId);
                mVerdicts.put(verdict.videoId, verdict);
                mVerdictTimes.put(verdict.videoId, mClock.now());
                isChanged = true;
            }
        }

        while (mVerdicts.size() > MAX_VERDICTS) {
            String oldest = mVerdicts.keySet().iterator().next();
            mVerdicts.remove(oldest);
            mVerdictTimes.remove(oldest);
        }

        if (isChanged) {
            writeVerdicts();
        }
    }

    private void readVerdicts() {
        if (mVerdicts != null) {
            return;
        }

        mVerdicts = new LinkedHashMap<>();
        mVerdictTimes = new LinkedHashMap<>();

        if (mScope == null) {
            return;
        }

        File file = new File(new File(mRoot, mScope), VERDICTS_FILE);
        JSONObject json = readJson(file);

        if (json == null) {
            return;
        }

        JSONArray entries = json.optJSONArray("entries");

        for (int i = 0; entries != null && i < entries.length(); i++) {
            JSONObject entry = entries.optJSONObject(i);
            JSONObject verdictJson = entry != null ? entry.optJSONObject("verdict") : null;

            if (verdictJson == null || isExpired(entry.optLong("at", 0))) {
                continue;
            }

            Verdict verdict = UtubotParser.parseVerdict(verdictJson);

            if (verdict.videoId != null && verdict.isReady()) {
                mVerdicts.put(verdict.videoId, verdict);
                mVerdictTimes.put(verdict.videoId, entry.optLong("at", 0));
            }
        }
    }

    private void writeVerdicts() {
        try {
            JSONArray entries = new JSONArray();

            for (Map.Entry<String, Verdict> entry : mVerdicts.entrySet()) {
                JSONObject item = new JSONObject();
                item.put("at", mVerdictTimes.get(entry.getKey()));
                item.put("verdict", toJson(entry.getValue()));
                entries.put(item);
            }

            writeJson(new File(new File(mRoot, mScope), VERDICTS_FILE), new JSONObject().put("entries", entries));
        } catch (JSONException | IOException e) {
            Log.e(TAG, "Can't store the verdicts: %s", e.getMessage());
        }
    }

    static JSONObject toJson(Verdict verdict) throws JSONException {
        JSONObject json = new JSONObject();
        json.put("video_id", verdict.videoId);
        json.put("status", verdict.status);
        json.put("action", verdict.action);
        json.put("mark_label", verdict.markLabel);
        json.put("title_question", verdict.titleQuestion);
        json.put("answer_short", verdict.answerShort);
        json.put("insight_ready", verdict.insightReady);
        json.put("captions_ready", verdict.captionsReady);
        JSONArray flags = new JSONArray();

        for (Flag flag : verdict.flags) {
            flags.put(new JSONObject()
                    .put("kind", flag.kind)
                    .put("label", flag.label)
                    .put("severity", flag.severity)
                    .put("reason", flag.reason));
        }

        json.put("flags", flags);
        return json;
    }

    //endregion

    //region Summaries

    @Nullable
    public synchronized Summary getSummary(String videoId, @Nullable String promptKey) {
        File file = summaryFile(videoId, promptKey);

        if (file == null || !file.isFile()) {
            return null;
        }

        JSONObject json = readJson(file);
        Summary summary = null;

        if (json != null && !isExpired(json.optLong("at", 0))) {
            summary = new Summary();
            summary.videoId = json.optString("video_id", null);
            summary.prompt = json.isNull("prompt") ? null : json.optString("prompt", null);
            summary.text = json.isNull("text") ? null : json.optString("text", null);
            summary.source = json.isNull("source") ? null : json.optString("source", null);
            summary.status = UtubotModels.STATUS_READY;
        }

        if (summary == null || !videoId.equals(summary.videoId) || summary.text == null || summary.text.isEmpty()) {
            file.delete();
            return null;
        }

        return summary;
    }

    /**
     * Stores a ready summary; the oldest are dropped beyond {@link #MAX_SUMMARIES}
     */
    public synchronized void putSummary(@Nullable String promptKey, Summary summary) {
        File file = summaryFile(summary.videoId, promptKey);

        if (file == null || !summary.isReady() || summary.isTransient() || summary.text == null || summary.text.isEmpty()) {
            return;
        }

        try {
            JSONObject json = new JSONObject();
            json.put("at", mClock.now());
            json.put("video_id", summary.videoId);
            json.put("prompt", summary.prompt);
            json.put("text", summary.text);
            json.put("source", summary.source);
            writeJson(file, json);
        } catch (JSONException | IOException e) {
            Log.e(TAG, "Can't store the summary of %s: %s", summary.videoId, e.getMessage());
            return;
        }

        trimSummaries(file.getParentFile());
    }

    /**
     * Forgets every summary of every scope: the default prompt or the prompt sets changed, so a stored text may not be the answer to the
     * same request anymore. A scope that has not been opened yet (or the connection it names is the previous one) is cleared too: a
     * summary stored by an earlier run must not come back when its scope opens.
     */
    public synchronized void clearSummaries() {
        File[] scopes = mRoot.listFiles();

        if (scopes == null) {
            return;
        }

        for (File scope : scopes) {
            deleteRecursively(new File(scope, SUMMARIES_DIRECTORY));
        }
    }

    public synchronized int summaryCount() {
        File[] files = mScope != null ? new File(new File(mRoot, mScope), SUMMARIES_DIRECTORY).listFiles() : null;
        return files != null ? files.length : 0;
    }

    @Nullable
    private File summaryFile(@Nullable String videoId, @Nullable String promptKey) {
        // The id is part of a file name: only what a video id can be
        if (mScope == null || videoId == null || !videoId.matches("[A-Za-z0-9_-]{1,32}")) {
            return null;
        }

        return new File(new File(new File(mRoot, mScope), SUMMARIES_DIRECTORY), videoId + "-" + promptHash(promptKey) + ".json");
    }

    static String promptHash(@Nullable String promptKey) {
        return sha256(promptKey != null ? promptKey : "").substring(0, PROMPT_HASH_LENGTH);
    }

    private static void trimSummaries(File directory) {
        File[] files = directory.listFiles((dir, name) -> name.endsWith(".json"));

        if (files == null || files.length <= MAX_SUMMARIES) {
            return;
        }

        Arrays.sort(files, Comparator.comparingLong(File::lastModified));

        for (int i = 0; i < files.length - MAX_SUMMARIES; i++) {
            files[i].delete();
        }
    }

    //endregion

    //region Cuts

    /**
     * The stored cut lists that have not expired, oldest first
     */
    public synchronized List<CutListCache> loadCuts() {
        File directory = cutsDirectory();

        if (directory == null) {
            return new ArrayList<>();
        }

        File[] files = directory.listFiles((dir, name) -> name.endsWith(".json"));
        List<CutListCache> result = new ArrayList<>();

        if (files == null) {
            return result;
        }

        Arrays.sort(files, Comparator.comparingLong(File::lastModified));

        for (File file : files) {
            CutListCache entry = readCut(file);

            if (entry != null) {
                result.add(entry);
            }
        }

        return result;
    }

    /**
     * The stored cut list of a video, with the ETag it was cached under, or null when there is none (or it
     * expired): a ready cut list is cheap to show at once when the backend is slow or down.
     */
    @Nullable
    public synchronized CutListCache getCuts(String videoId) {
        File file = cutsFile(videoId);

        if (file == null) {
            return null;
        }

        return readCut(file);
    }

    /**
     * Reads one cut list file, or null when it is missing, expired, damaged or not the video's
     */
    @Nullable
    private CutListCache readCut(File file) {
        JSONObject json = readJson(file);

        if (json == null || isExpired(json.optLong("at", 0))) {
            return null;
        }

        if (json.isNull("body")) {
            file.delete();
            return null;
        }

        try {
            return new CutListCache(UtubotParser.parseCuts(json.optString("body", null)),
                    json.isNull("video_id") ? null : json.optString("video_id", null),
                    json.isNull("etag") ? null : json.optString("etag", null));
        } catch (JSONException e) {
            Log.e(TAG, "Dropping the damaged cut list %s: %s", file.getName(), e.getMessage());
            file.delete();
            return null;
        }
    }

    /**
     * Stores a cut list with the ETag it came with; the oldest are dropped beyond {@link #MAX_CUTS}
     */
    public synchronized void putCuts(String videoId, @Nullable String etag, @Nullable String body) {
        File file = cutsFile(videoId);

        if (file == null || body == null) {
            return;
        }

        try {
            JSONObject json = new JSONObject();
            json.put("at", mClock.now());
            json.put("video_id", videoId);
            json.put("etag", etag != null ? etag : "");
            json.put("body", body);
            writeJson(file, json);
        } catch (JSONException | IOException e) {
            Log.e(TAG, "Can't store the cut list of %s: %s", videoId, e.getMessage());
            return;
        }

        trimCuts(file.getParentFile());
    }

    /**
     * Forgets every cut list of every scope: a change of backend, token or version means the stored lists are
     * not the answers of the new connection, and a scope opened later starts empty.
     */
    public synchronized void clearCuts() {
        File[] scopes = mRoot.listFiles();

        if (scopes == null) {
            return;
        }

        for (File scope : scopes) {
            deleteRecursively(new File(scope, CUTS_DIRECTORY));
        }
    }

    @Nullable
    private File cutsFile(@Nullable String videoId) {
        // The id is part of a file name: only what a video id can be
        if (mScope == null || videoId == null || !videoId.matches("[A-Za-z0-9_-]{1,32}")) {
            return null;
        }

        return new File(new File(new File(mRoot, mScope), CUTS_DIRECTORY), videoId + ".json");
    }

    @Nullable
    private File cutsDirectory() {
        if (mScope == null) {
            return null;
        }

        return new File(new File(mRoot, mScope), CUTS_DIRECTORY);
    }

    private static void trimCuts(File directory) {
        File[] files = directory.listFiles((dir, name) -> name.endsWith(".json"));

        if (files == null || files.length <= MAX_CUTS) {
            return;
        }

        Arrays.sort(files, Comparator.comparingLong(File::lastModified));

        for (int i = 0; i < files.length - MAX_CUTS; i++) {
            files[i].delete();
        }
    }

    //endregion

    private boolean isExpired(long storedAt) {
        long age = mClock.now() - storedAt;
        return age < 0 || age > TTL_MS;
    }

    @Nullable
    private static JSONObject readJson(File file) {
        if (!file.isFile()) {
            return null;
        }

        try (InputStream stream = new FileInputStream(file)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] chunk = new byte[CHUNK_BYTES];
            int read;

            while ((read = stream.read(chunk)) != -1) {
                out.write(chunk, 0, read);

                if (out.size() > MAX_FILE_BYTES) {
                    throw new IOException("too large");
                }
            }

            return new JSONObject(out.toString(StandardCharsets.UTF_8.name()));
        } catch (IOException | JSONException e) {
            Log.e(TAG, "Dropping the damaged cache file %s: %s", file.getName(), e.getMessage());
            file.delete();
            return null;
        }
    }

    private static void writeJson(File file, JSONObject json) throws IOException {
        File directory = file.getParentFile();

        if (!directory.isDirectory() && !directory.mkdirs()) {
            throw new IOException("Can't create " + directory);
        }

        File temp = new File(directory, file.getName() + TEMP_EXTENSION);

        try (FileOutputStream stream = new FileOutputStream(temp)) {
            stream.write(json.toString().getBytes(StandardCharsets.UTF_8));
        }

        if (!temp.renameTo(file)) {
            temp.delete();
            throw new IOException("Can't replace " + file);
        }
    }

    private static void deleteRecursively(File file) {
        File[] children = file.listFiles();

        if (children != null) {
            for (File child : children) {
                deleteRecursively(child);
            }
        }

        file.delete();
    }

    private static String sha256(String text) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();

            for (byte b : hash) {
                hex.append(String.format("%02x", b));
            }

            return hex.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
