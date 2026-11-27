package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.speech.SpeechRecognizer;
import android.speech.RecognizerIntent;
import androidx.annotation.Nullable;
import androidx.core.app.ActivityCompat;

import com.liskovsoft.smartyoutubetv2.common.misc.MotherActivity;

import java.io.IOException;
import java.util.ArrayList;

/**
 * Describe something by voice: capture the TV's microphone, transcribe it through the backend's
 * speech-to-text (`POST /v1/speech`), return the text. The capture is pluggable ({@link Capture})
 * so the record → WAV → upload pipeline is unit-tested with a fake, while the real
 * {@link android.media.AudioRecord} and the platform recogniser live in {@link AudioCapture}.
 *
 * The capture runs on a worker thread (recording blocks, and the upload is network). When the
 * microphone cannot be opened the platform {@code SpeechRecognizer} (text only) is the fallback.
 * The permission and recogniser results come through {@link #onUtubotSpeechActivityResult}.
 */
public final class UtubotSpeechInput implements UtubotSpeechActivityHost {
    static final String PROGRESS_RECORDING = "Recording…";
    static final String ERROR_NO_MIC = "This TV has no usable microphone; type the description.";
    static final String ERROR_EMPTY = "The recording had no speech; try again or type it.";

    static final int REQUEST_PERMISSION = 0x91;
    private static final int MS_PER_SECOND = 1000;
    static final int REQUEST_SPEECH = 0x92;

    /** Backend default recording budget; the backend enforces the real limit server-side. */
    public static final int DEFAULT_MAX_SECONDS = 50;

    /** Records audio, or returns the platform recogniser's text directly. Pluggable for tests. */
    public interface Capture {
        /** Records up to {@code maxDurationMs} (blocking; call off the main thread) and reports through {@code result}. */
        void record(int maxDurationMs, Result result);

        /** Ends the recording now and keeps what was heard so far. */
        void stop();

        /** Ends the recording now and throws it away. */
        void cancel();

        interface Result {
            void onProgress(String message);

            void onPcm(short[] pcm, int sampleRate, int channels);

            void onText(String text);

            void onError(String message);
        }
    }

    /** The result of a describe call; delivered on a worker thread, so a view posts to its own thread. */
    public interface Listener {
        void onProgress(String message);

        void onText(String text);

        void onError(String message);
    }

    private final Context mContext;
    private final UtubotClient mClient;
    private final Capture mCapture;
    private volatile boolean mCancelled;
    private volatile boolean mAwaitingPermission;
    @Nullable private String mLanguageHint;
    private int mMaxSeconds;
    @Nullable private Listener mListener;
    @Nullable private Capture.Result mCaptureResult;
    @Nullable private Capture.Result mSpeechResult;

    public UtubotSpeechInput(Context context, UtubotClient client) {
        this(context, client, new AudioCapture());
    }

    UtubotSpeechInput(Context context, UtubotClient client, Capture capture) {
        mContext = context;
        mClient = client;
        mCapture = capture;
    }

    /**
     * Record, transcribe, and report through the listener.
     *
     * @param languageHint the caller's language, or null to follow the server's default
     * @param maxSeconds the recording cap (the backend's {@code speech_max_s})
     */
    public synchronized void describe(@Nullable String languageHint, int maxSeconds, Listener listener) {
        if (listener == null) {
            return;
        }

        mCancelled = false;
        mLanguageHint = languageHint;
        mMaxSeconds = maxSeconds;
        mListener = listener;
        mAwaitingPermission = false;
        listener.onProgress(PROGRESS_RECORDING);

        Activity activity = activityOf(mContext);

        if (activity != null && ActivityCompat.checkSelfPermission(activity, android.Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            if (activity instanceof MotherActivity) {
                ((MotherActivity) activity).addOnPermissions(this::onPermissions);
            }
            ActivityCompat.requestPermissions(activity, new String[]{android.Manifest.permission.RECORD_AUDIO}, REQUEST_PERMISSION);
            mAwaitingPermission = true;
            return;
        }

        startCapture();
    }

    private void startCapture() {
        mCaptureResult = new Capture.Result() {
            @Override
            public void onProgress(String message) {
                mListener.onProgress(message);
            }

            @Override
            public void onPcm(short[] pcm, int sampleRate, int channels) {
                uploadPcm(pcm, sampleRate, channels);
            }

            @Override
            public void onText(String text) {
                finish(text);
            }

            @Override
            public void onError(String message) {
                onCaptureError(message);
            }
        };
        Capture.Result result = mCaptureResult;
        Thread worker = new Thread(() -> mCapture.record(mMaxSeconds * MS_PER_SECOND, result), "utubot-speech");
        worker.setDaemon(true);
        worker.start();
    }

    private synchronized void onPermissions(int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode != REQUEST_PERMISSION || !mAwaitingPermission) {
            return;
        }

        mAwaitingPermission = false;

        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCapture();
        } else {
            fail(ERROR_NO_MIC);
        }
    }

    private void uploadPcm(short[] pcm, int sampleRate, int channels) {
        if (mCancelled) {
            return;
        }

        byte[] wav = UtubotWav.encode(pcm, sampleRate, channels);

        try {
            finish(mClient.speech(wav, "recording.wav", "audio/wav", mLanguageHint));
        } catch (IOException e) {
            fail(e.getMessage() != null ? e.getMessage() : ERROR_EMPTY);
        }
    }

    private void onCaptureError(String message) {
        // No usable raw capture: fall back to the platform recogniser, which returns text only.
        if (ERROR_NO_MIC.equals(message)) {
            startSpeechRecognizer();
            return;
        }
        fail(message);
    }

    private void startSpeechRecognizer() {
        Activity activity = activityOf(mContext);

        if (activity == null || !SpeechRecognizer.isRecognitionAvailable(activity)) {
            fail(ERROR_NO_MIC);
            return;
        }

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, activity.getPackageName());

        if (mLanguageHint != null && !mLanguageHint.isEmpty()) {
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, mLanguageHint);
        }

        mSpeechResult = new Capture.Result() {
            @Override
            public void onProgress(String message) {
            }

            @Override
            public void onPcm(short[] pcm, int sampleRate, int channels) {
            }

            @Override
            public void onText(String text) {
                finish(text);
            }

            @Override
            public void onError(String message) {
                fail(message);
            }
        };

        try {
            activity.startActivityForResult(intent, REQUEST_SPEECH);
        } catch (android.content.ActivityNotFoundException ignored) {
            // No recogniser on this TV: the microphone path already failed, so report it plainly.
            fail(ERROR_NO_MIC);
        }
    }

    @Override
    public synchronized void onUtubotSpeechActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQUEST_SPEECH) {
            if (mSpeechResult == null) {
                return;
            }

            if (resultCode == Activity.RESULT_OK && data != null) {
                ArrayList<String> matches = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);

                if (matches != null && !matches.isEmpty()) {
                    mSpeechResult.onText(String.join(" ", matches));
                    return;
                }
            }

            fail(ERROR_NO_MIC);
        }
    }

    private void finish(@Nullable String text) {
        if (mCancelled || mListener == null) {
            return;
        }

        String trimmed = text == null ? "" : text.trim();

        if (trimmed.isEmpty()) {
            fail(ERROR_EMPTY);
            return;
        }

        mListener.onText(trimmed);
    }

    private void fail(String message) {
        if (mCancelled || mListener == null) {
            return;
        }

        mListener.onError(message);
    }

    /** Ends the recording and transcribes what was heard (the "tap to stop" of the sheet). */
    public void stopRecording() {
        mCapture.stop();
    }

    /** Stops the capture and releases the microphone; safe to call from any thread. */
    public synchronized void cancel() {
        mCancelled = true;
        mCapture.cancel();
    }

    @Nullable
    private static Activity activityOf(Context context) {
        Context current = context;

        while (current instanceof ContextWrapper && !(current instanceof Activity)) {
            current = ((ContextWrapper) current).getBaseContext();
        }

        return current instanceof Activity ? (Activity) current : null;
    }
}
