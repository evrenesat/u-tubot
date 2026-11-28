package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;
import androidx.annotation.VisibleForTesting;

import com.liskovsoft.smartyoutubetv2.common.diagnostics.ReportRedaction;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReferenceArray;

/**
 * The player's event log: events go into a bounded ring in memory (an object per event, nothing written, nothing formatted), and a
 * background thread appends them to a small rotating file on a crash, on an error, when playback pauses or stops, and every
 * {@link #FLUSH_EVERY_MS} while there is something new. Nothing in the player's threads touches the disk. {@link #event} costs a
 * counter increment and a store; callers that build a detail string check {@link #isEnabled()} first.
 */
public final class UtubotPlayerLog {
    static final int RING_SIZE = 512;
    static final long MAX_FILE_BYTES = 256 * 1024;
    static final int MAX_FILES = 3;
    public static final long FLUSH_EVERY_MS = 5 * 60_000;
    private static final String DIR = "utubot_player_log";
    private static final String CURRENT = "events.log";
    private static final int MAX_DETAIL_CHARS = 300;
    private static final int ERROR_FRAMES = 6;
    private static final String DROPPED = "dropped";
    @SuppressLint("StaticFieldLeak")
    private static volatile UtubotPlayerLog sInstance;
    private static volatile boolean sEnabled = true;
    private static volatile String sScreen = "";

    private static final class Entry {
        final long ts;
        final long seq;
        final String name;
        @Nullable
        final String detail;

        Entry(long ts, long seq, String name, @Nullable String detail) {
            this.ts = ts;
            this.seq = seq;
            this.name = name;
            this.detail = detail;
        }
    }

    private final File mDir;
    private final long mMaxFileBytes;
    private final int mMaxFiles;
    private final AtomicReferenceArray<Entry> mRing;
    private final int mRingSize;
    private final AtomicLong mSeq = new AtomicLong();
    private final Object mFileLock = new Object();
    private long mFlushedSeq;
    private final ScheduledExecutorService mExecutor = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "utubot-player-log");
        thread.setDaemon(true);
        thread.setPriority(Thread.MIN_PRIORITY);
        return thread;
    });

    @VisibleForTesting
    UtubotPlayerLog(File dir, int ringSize, long maxFileBytes, int maxFiles) {
        mDir = dir;
        mRingSize = ringSize;
        mRing = new AtomicReferenceArray<>(ringSize);
        mMaxFileBytes = maxFileBytes;
        mMaxFiles = maxFiles;
    }

    /**
     * Once, from the application: the log and its periodic flush
     */
    public static synchronized void init(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotPlayerLog(new File(context.getFilesDir(), DIR), RING_SIZE, MAX_FILE_BYTES, MAX_FILES);
            sInstance.mExecutor.scheduleWithFixedDelay(sInstance::flushIfPending, FLUSH_EVERY_MS, FLUSH_EVERY_MS, TimeUnit.MILLISECONDS);
        }
    }

    @VisibleForTesting
    public static void useForTesting(@Nullable UtubotPlayerLog log) {
        sInstance = log;
    }

    @VisibleForTesting
    public static UtubotPlayerLog createForTesting(File dir, int ringSize, long maxFileBytes, int maxFiles) {
        return new UtubotPlayerLog(dir, ringSize, maxFileBytes, maxFiles);
    }

    public static boolean isEnabled() {
        return sEnabled && sInstance != null;
    }

    public static void setEnabled(boolean enabled) {
        sEnabled = enabled;
    }

    public static void event(String name) {
        event(name, null);
    }

    /**
     * @param detail built by the caller only after {@link #isEnabled()}; never a stream address (it is redacted on the way out, but
     * is not to be put in at all)
     */
    public static void event(String name, @Nullable String detail) {
        UtubotPlayerLog log = sInstance;

        if (log != null && sEnabled) {
            log.append(name, detail);
        }
    }

    /**
     * A caught exception that playback goes on from, or the player's own error: the log is written soon after
     */
    public static void error(String name, @Nullable Throwable error) {
        UtubotPlayerLog log = sInstance;

        if (log == null || !sEnabled) {
            return;
        }

        log.append(name, describe(error));
        log.flushAsync();
    }

    public static void flushAsync() {
        UtubotPlayerLog log = sInstance;

        if (log != null) {
            log.flushAsyncInternal();
        }
    }

    /**
     * Written before it returns, on the calling thread: from the crash handler only
     */
    public static void flushNow() {
        UtubotPlayerLog log = sInstance;

        if (log != null) {
            log.flush();
        }
    }

    /**
     * The newest events as text, oldest first, for a crash report
     */
    public static List<String> tail(int max) {
        UtubotPlayerLog log = sInstance;

        return log != null ? log.recent(max) : Collections.emptyList();
    }

    /**
     * The files written so far, oldest first, after what is in memory was written
     */
    public static List<File> filesForUpload() {
        UtubotPlayerLog log = sInstance;

        if (log == null) {
            return Collections.emptyList();
        }

        log.flush();

        return log.files();
    }

    /**
     * After the server confirmed the upload: what was read is gone, what was written since stays
     */
    public static void deleteUploaded(List<File> files) {
        UtubotPlayerLog log = sInstance;

        if (log != null) {
            log.delete(files);
        }
    }

    void append(String name, @Nullable String detail) {
        long seq = mSeq.getAndIncrement();
        String text = detail != null && detail.length() > MAX_DETAIL_CHARS ? detail.substring(0, MAX_DETAIL_CHARS) : detail;
        mRing.set((int) (seq % mRingSize), new Entry(System.currentTimeMillis(), seq, name, text));
    }

    void flushAsyncInternal() {
        try {
            mExecutor.execute(this::flush);
        } catch (RuntimeException e) {
            // Shut down: nothing to write
        }
    }

    void flushIfPending() {
        if (mSeq.get() > mFlushedSeq) {
            flush();
        }
    }

    /**
     * Appends what is new since the last flush, redacted. Never throws.
     */
    void flush() {
        synchronized (mFileLock) {
            try {
                List<Entry> entries = snapshot(mFlushedSeq);

                if (entries.isEmpty()) {
                    return;
                }

                StringBuilder text = new StringBuilder();
                long expected = mFlushedSeq;

                for (Entry entry : entries) {
                    if (entry.seq > expected) {
                        text.append(format(entry.ts, DROPPED, (entry.seq - expected) + " events")).append('\n');
                    }

                    text.append(format(entry.ts, entry.name, entry.detail)).append('\n');
                    expected = entry.seq + 1;
                }

                write(text.toString());
                mFlushedSeq = expected;
            } catch (IOException | RuntimeException e) {
                // The log is not worth a failure of the player
            }
        }
    }

    private List<Entry> snapshot(long fromSeq) {
        List<Entry> entries = new ArrayList<>();

        for (int i = 0; i < mRingSize; i++) {
            Entry entry = mRing.get(i);

            if (entry != null && entry.seq >= fromSeq) {
                entries.add(entry);
            }
        }

        Collections.sort(entries, (a, b) -> Long.compare(a.seq, b.seq));

        return entries;
    }

    private List<String> recent(int max) {
        List<Entry> entries = snapshot(0);
        List<String> lines = new ArrayList<>();

        for (int i = Math.max(0, entries.size() - max); i < entries.size(); i++) {
            Entry entry = entries.get(i);
            lines.add(format(entry.ts, entry.name, entry.detail));
        }

        return lines;
    }

    private static String format(long ts, String name, @Nullable String detail) {
        // Per call: SimpleDateFormat is not thread safe, and this runs off the player's threads
        String time = new SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US).format(new Date(ts));

        return time + " " + name + (detail == null || detail.isEmpty() ? "" : " " + ReportRedaction.redact(detail));
    }

    private void write(String text) throws IOException {
        if (!mDir.isDirectory() && !mDir.mkdirs()) {
            throw new IOException("no directory");
        }

        File current = new File(mDir, CURRENT);

        if (current.length() + text.length() > mMaxFileBytes && current.length() > 0) {
            rotate();
        }

        try (FileOutputStream out = new FileOutputStream(current, true)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
    }

    private void rotate() {
        new File(mDir, name(mMaxFiles - 1)).delete();

        for (int i = mMaxFiles - 2; i >= 0; i--) {
            File from = new File(mDir, name(i));

            if (from.exists()) {
                from.renameTo(new File(mDir, name(i + 1)));
            }
        }
    }

    private static String name(int index) {
        return index == 0 ? CURRENT : "events." + index + ".log";
    }

    List<File> files() {
        List<File> files = new ArrayList<>();

        synchronized (mFileLock) {
            for (int i = mMaxFiles - 1; i >= 0; i--) {
                File file = new File(mDir, name(i));

                if (file.isFile() && file.length() > 0) {
                    files.add(file);
                }
            }
        }

        return files;
    }

    void delete(List<File> files) {
        synchronized (mFileLock) {
            for (File file : files) {
                file.delete();
            }
        }
    }

    public static String describeForCrash(@Nullable Throwable error) {
        return describe(error);
    }

    /**
     * Where the user is, for a crash report: the view on top (set by {@link #setScreen})
     */
    public static String screen() {
        return sScreen;
    }

    public static void setScreen(String screen) {
        sScreen = screen;
    }

    static String describe(@Nullable Throwable error) {
        if (error == null) {
            return "unknown";
        }

        StringBuilder text = new StringBuilder(error.getClass().getSimpleName()).append(": ").append(error.getMessage());
        StackTraceElement[] frames = error.getStackTrace();

        for (int i = 0; i < Math.min(ERROR_FRAMES, frames.length); i++) {
            text.append(" | ").append(frames[i].getClassName().replaceAll("^.*\\.", "")).append('.').append(frames[i].getMethodName())
                    .append(':').append(frames[i].getLineNumber());
        }

        return text.toString();
    }
}
