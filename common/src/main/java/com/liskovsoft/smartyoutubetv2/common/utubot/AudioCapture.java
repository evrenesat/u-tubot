package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import androidx.annotation.Nullable;

import java.util.Arrays;

/**
 * The real {@link UtubotSpeechInput.Capture}: the TV's {@link AudioRecord} on the voice-recognition
 * source, read as 16 kHz 16-bit mono PCM (so 50 s stays under the backend's upload cap as an
 * uncompressed WAV). It blocks until the maximum length, {@link #stop()} (the owner tapped stop) or
 * {@link #cancel()}. A recorder that cannot start reports {@link #ERROR_NO_MIC} (the caller then
 * falls back to the platform recogniser); a recording that is silent reports
 * {@link UtubotSpeechInput#ERROR_EMPTY}.
 */
final class AudioCapture implements UtubotSpeechInput.Capture {
    static final int SAMPLE_RATE = 16_000;
    static final int BUFFER_SAMPLES = 1_600; // 100 ms chunks
    private static final int MS_PER_SECOND = 1000;

    static final String ERROR_NO_MIC = UtubotSpeechInput.ERROR_NO_MIC;

    @Nullable private volatile AudioRecord mRecord;
    private volatile boolean mStopped;
    private volatile boolean mCancelled;

    @Override
    public void record(int maxDurationMs, Result result) {
        mStopped = false;
        mCancelled = false;

        short[] pcm = capture(maxDurationMs);

        if (mCancelled) {
            return;
        }

        if (pcm == null) {
            result.onError(ERROR_NO_MIC);
        } else if (!UtubotSpeechProbe.isUsable(pcm)) {
            result.onError(UtubotSpeechInput.ERROR_EMPTY);
        } else {
            result.onPcm(pcm, SAMPLE_RATE, 1);
        }
    }

    /** The PCM heard until the cap or a stop; null when the recorder could not run or read nothing. */
    @Nullable
    private short[] capture(int maxDurationMs) {
        int bufferSize = Math.max(
                AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT),
                BUFFER_SAMPLES * 2);
        AudioRecord record;

        try {
            record = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferSize);
        } catch (Exception ignored) {
            return null;
        }

        if (record.getState() != AudioRecord.STATE_INITIALIZED) {
            record.release();
            return null;
        }

        int totalSamples = SAMPLE_RATE * maxDurationMs / MS_PER_SECOND;
        short[] all = new short[totalSamples];
        short[] chunk = new short[BUFFER_SAMPLES];
        int read = 0;

        try {
            mRecord = record;
            record.startRecording();

            while (read < totalSamples && !mStopped && !mCancelled) {
                int n = record.read(chunk, 0, Math.min(chunk.length, totalSamples - read));

                if (n < 0) {
                    break;
                }

                System.arraycopy(chunk, 0, all, read, n);
                read += n;
            }
        } catch (Exception ignored) {
            // The recorder stopped out from under us (a call, a device change): keep what was read.
        } finally {
            release(record);
        }

        return read <= 0 ? null : Arrays.copyOf(all, read);
    }

    private void release(AudioRecord record) {
        try {
            record.stop();
        } catch (Exception ignored) {
            // Not recording: nothing to stop.
        }
        record.release();

        if (mRecord == record) {
            mRecord = null;
        }
    }

    @Override
    public void stop() {
        mStopped = true;
    }

    @Override
    public void cancel() {
        mCancelled = true;
    }
}
