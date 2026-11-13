package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.regex.Pattern;

/**
 * The HQ caption files the TV downloaded, kept in its own storage: they survive a restart and an update of the app, are played without
 * the backend, and the subtitle menu offers them for their video from then on. Nothing is ever removed or replaced here: a track that is
 * stored stays as it was first stored. Layout: {@code <root>/<video id>/<lang>.vtt} plus {@code index.json} with the labels. The files
 * are the truth: a lost or damaged index only costs the labels.
 */
public final class UtubotCaptionStore {
    public static final String DIRECTORY = "utubot_captions";
    /** A caption file is a few hundred KB at most; a larger answer is not one */
    public static final int MAX_FILE_BYTES = 4 * 1024 * 1024;
    private static final String INDEX_FILE = "index.json";
    private static final String FILE_EXTENSION = ".vtt";
    private static final String TEMP_EXTENSION = ".tmp";
    private static final int CHUNK_BYTES = 4096;
    private static final String VTT_HEADER = "WEBVTT";
    private static final String BYTE_ORDER_MARK = "﻿";
    private static final Pattern VIDEO_ID = Pattern.compile("[A-Za-z0-9_-]{11}");
    private static final Pattern LANGUAGE = Pattern.compile("[A-Za-z0-9_-]{1,32}");
    private static final String KEY_TRACKS = "tracks";
    private static final String KEY_LANG = "lang";
    private static final String KEY_LABEL = "label";
    private static final String KEY_SPEAKERS = "speakers";
    private static final String TAG = UtubotCaptionStore.class.getSimpleName();
    @SuppressLint("StaticFieldLeak")
    private static UtubotCaptionStore sInstance;
    private final File mRoot;

    public static final class StoredTrack {
        public final String lang;
        public final String label;
        public final int speakers;
        public final File file;

        StoredTrack(String lang, String label, int speakers, File file) {
            this.lang = lang;
            this.label = label;
            this.speakers = speakers;
            this.file = file;
        }
    }

    public UtubotCaptionStore(File root) {
        mRoot = root;
    }

    public static synchronized UtubotCaptionStore instance(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotCaptionStore(new File(context.getApplicationContext().getFilesDir(), DIRECTORY));
        }

        return sInstance;
    }

    File root() {
        return mRoot;
    }

    /**
     * The tracks stored for the video, by language. Empty when there are none, and for a video id that is not one.
     */
    public synchronized List<StoredTrack> tracks(@Nullable String videoId) {
        File dir = directoryOf(videoId);
        File[] files = dir != null ? dir.listFiles((parent, name) -> name.endsWith(FILE_EXTENSION)) : null;

        if (files == null) {
            return Collections.emptyList();
        }

        JSONArray index = readIndex(dir);
        List<StoredTrack> tracks = new ArrayList<>();

        for (File file : files) {
            String lang = file.getName().substring(0, file.getName().length() - FILE_EXTENSION.length());

            if (file.length() > 0 && LANGUAGE.matcher(lang).matches()) {
                tracks.add(describe(index, lang, file));
            }
        }

        Collections.sort(tracks, (first, second) -> first.lang.compareTo(second.lang));

        return tracks;
    }

    public synchronized boolean has(@Nullable String videoId) {
        return !tracks(videoId).isEmpty();
    }

    public synchronized boolean hasTrack(@Nullable String videoId, @Nullable String lang) {
        for (StoredTrack track : tracks(videoId)) {
            if (track.lang.equals(lang)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Keeps the file of a track. A track of that video and language that is stored already is left as it is.
     *
     * @return the stored track, null when nothing was stored: a video id or language that can't be a file name, a file that isn't WebVTT or
     * is too large, or the storage refused it
     */
    @Nullable
    public synchronized StoredTrack save(@Nullable String videoId, CaptionTrack track, byte[] vtt) {
        File dir = directoryOf(videoId);

        if (dir == null || track.lang == null || !LANGUAGE.matcher(track.lang).matches() || !isWebVtt(vtt)) {
            return null;
        }

        File file = new File(dir, track.lang + FILE_EXTENSION);

        for (StoredTrack stored : tracks(videoId)) {
            if (stored.lang.equals(track.lang)) {
                return stored;
            }
        }

        try {
            if (!dir.isDirectory() && !dir.mkdirs()) {
                throw new IOException("Can't create " + dir);
            }

            writeAtomically(file, vtt);
            writeIndex(dir, track);
        } catch (IOException e) {
            Log.e(TAG, "Can't keep the captions of %s: %s", videoId, e.getMessage());

            if (!file.isFile()) {
                return null;
            }
        }

        return describe(readIndex(dir), track.lang, file);
    }

    private static boolean isWebVtt(byte[] vtt) {
        if (vtt.length == 0 || vtt.length > MAX_FILE_BYTES) {
            return false;
        }

        String head = new String(vtt, 0, Math.min(vtt.length, VTT_HEADER.length() + BYTE_ORDER_MARK.length() * 3), StandardCharsets.UTF_8);

        return (head.startsWith(BYTE_ORDER_MARK) ? head.substring(BYTE_ORDER_MARK.length()) : head).startsWith(VTT_HEADER);
    }

    @Nullable
    private File directoryOf(@Nullable String videoId) {
        return videoId != null && VIDEO_ID.matcher(videoId).matches() ? new File(mRoot, videoId) : null;
    }

    private static StoredTrack describe(@Nullable JSONArray index, String lang, File file) {
        String label = lang;
        int speakers = 0;

        for (int i = 0; index != null && i < index.length(); i++) {
            JSONObject entry = index.optJSONObject(i);

            if (entry != null && lang.equals(entry.optString(KEY_LANG))) {
                label = entry.optString(KEY_LABEL, lang);
                speakers = entry.optInt(KEY_SPEAKERS);
            }
        }

        return new StoredTrack(lang, label, speakers, file);
    }

    @Nullable
    private static JSONArray readIndex(File dir) {
        File index = new File(dir, INDEX_FILE);

        if (!index.isFile()) {
            return null;
        }

        try {
            return new JSONObject(new String(readAll(index), StandardCharsets.UTF_8)).optJSONArray(KEY_TRACKS);
        } catch (IOException | JSONException e) {
            Log.e(TAG, "Damaged index of %s: %s", dir.getName(), e.getMessage());
            return null;
        }
    }

    /**
     * Adds the track to the labels. A damaged index is replaced: the files hold everything else.
     */
    private static void writeIndex(File dir, CaptionTrack track) throws IOException {
        JSONArray index = readIndex(dir);
        JSONArray tracks = new JSONArray();

        try {
            for (int i = 0; index != null && i < index.length(); i++) {
                JSONObject entry = index.optJSONObject(i);

                if (entry != null && !track.lang.equals(entry.optString(KEY_LANG))) {
                    tracks.put(entry);
                }
            }

            tracks.put(new JSONObject().put(KEY_LANG, track.lang).put(KEY_LABEL, track.label != null ? track.label : track.lang)
                    .put(KEY_SPEAKERS, track.speakers));
            writeAtomically(new File(dir, INDEX_FILE), new JSONObject().put(KEY_TRACKS, tracks).toString().getBytes(StandardCharsets.UTF_8));
        } catch (JSONException e) {
            throw new IOException(e);
        }
    }

    /**
     * The new content is complete or the old one stays: written next to the file and moved over it
     */
    private static void writeAtomically(File file, byte[] content) throws IOException {
        File temp = new File(file.getParentFile(), file.getName() + TEMP_EXTENSION);

        try (FileOutputStream out = new FileOutputStream(temp)) {
            out.write(content);
            out.getFD().sync();
        }

        // On the same storage a rename replaces the file in one step
        if (!temp.renameTo(file)) {
            temp.delete();
            throw new IOException("Can't move " + temp + " to " + file);
        }
    }

    private static byte[] readAll(File file) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] chunk = new byte[CHUNK_BYTES];

        try (InputStream in = new FileInputStream(file)) {
            int read;

            while ((read = in.read(chunk)) != -1) {
                out.write(chunk, 0, read);
            }
        }

        return out.toByteArray();
    }
}
