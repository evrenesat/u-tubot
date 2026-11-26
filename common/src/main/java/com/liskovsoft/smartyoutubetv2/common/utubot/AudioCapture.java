package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;

/**
 * The real {@link UtubotSpeechInput.Capture}: the TV's {@link AudioRecord}. It probes each
 * {@code AudioManager} input device (API 31+, recording a few seconds from each with
 * {@code setPreferredDevice} to see which one hears), picks the loudest usable one, and records the
 * full clip as 16-bit mono PCM. When no device delivers audio it reports {@link #ERROR_NO_MIC}, so
 * the caller falls back to the platform recogniser.
 *
 * The recording is 16 kHz mono so 50 s stays under the backend's upload cap as uncompressed WAV.
 */
final class AudioCapture implements UtubotSpeechInput.Capture {
    static final int SAMPLE_RATE = 16_000;
    static final int PROBE_DURATION_MS = 3_000;
    static final int BUFFER_SAMPLES = 1_600; // 100 ms chunks

    private static final int MIC_SOURCE = MediaRecorder.AudioSource.MIC;
    private static final int RECOGNITION_SOURCE = MediaRecorder.AudioSource.VOICE_RECOGNITION;

    static final String ERROR_NO_MIC = UtubotSpeechInput.ERROR_NO_MIC;

    private static final int[] INPUT_DEVICE_TYPES = {
        AudioDeviceInfo.TYPE_BUILTIN_MIC,
        AudioDeviceInfo.TYPE_BUILTIN_EARPIECE,
        AudioDeviceInfo.TYPE_WIRED_HEADSET,
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
        AudioDeviceInfo.TYPE_USB_HEADSET,
        AudioDeviceInfo.TYPE_USB_ACCESSORY,
        AudioDeviceInfo.TYPE_BLE_HEADSET,
        AudioDeviceInfo.TYPE_TELEPHONY,
    };

    private final Context mContext;
    @Nullable private volatile AudioRecord mRecord;
    private volatile boolean mCancelled;

    AudioCapture(Context context) {
        mContext = context.getApplicationContext();
    }

    @Override
    public void record(int durationMs, Result result) {
        mCancelled = false;

        AudioDeviceInfo[] devices = inputDevices();

        if (devices != null && devices.length > 0) {
            probeAndRecord(devices, durationMs, result);
        } else {
            // No way to list input devices (older API): try the default voice-recognition source.
            recordFrom(capture(RECOGNITION_SOURCE, null, durationMs), result);
        }
    }

    private void probeAndRecord(AudioDeviceInfo[] devices, int durationMs, Result result) {
        AudioManager audio = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);
        List<UtubotSpeechProbe.SpeechDeviceReading> readings = new ArrayList<>();

        for (AudioDeviceInfo device : devices) {
            if (!device.isSource()) {
                continue;
            }

            for (int source : new int[]{RECOGNITION_SOURCE, MIC_SOURCE}) {
                if (mCancelled) {
                    return;
                }

                short[] probe = capture(source, device, PROBE_DURATION_MS);
                readings.add(new UtubotSpeechProbe.SpeechDeviceReading(device.getId(), String.valueOf(device.getProductName()), source, UtubotSpeechProbe.measureRms(probe)));
                result.onProgress("Testing microphone: " + deviceLabel(device, source));
            }
        }

        int best = UtubotSpeechProbe.selectBest(readings);

        if (best < 0) {
            result.onError(ERROR_NO_MIC);
            return;
        }

        UtubotSpeechProbe.SpeechDeviceReading chosen = readings.get(best);
        short[] pcm = capture(chosen.source, deviceForId(devices, chosen.deviceId), durationMs);
        recordFrom(pcm, result);
    }

    private void recordFrom(@Nullable short[] pcm, Result result) {
        if (pcm == null) {
            result.onError(ERROR_NO_MIC);
        } else {
            result.onPcm(pcm, SAMPLE_RATE, 1);
        }
    }

    /**
     * Records {@code durationMs} from {@code source}, preferring {@code device}. Returns the PCM
     * samples, or null when the recorder could not run or read nothing.
     */
    @Nullable
    private short[] capture(int source, @Nullable AudioDeviceInfo device, int durationMs) {
        if (mCancelled) {
            return null;
        }

        AudioFormat format = new AudioFormat.Builder()
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setSampleRate(SAMPLE_RATE)
                .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                .build();

        int bufferSize = Math.max(
                AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT),
                BUFFER_SAMPLES * 2);

        AudioRecord record;

        try {
            record = new AudioRecord(source, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferSize);
        } catch (Exception ignored) {
            return null;
        }

        if (device != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            record.setPreferredDevice(device);
        }

        if (mCancelled) {
            release(record);
            return null;
        }

        record.startRecording();
        mRecord = record;

        int totalSamples = SAMPLE_RATE * durationMs / 1000;
        short[] all = new short[totalSamples];
        int read = 0;
        short[] chunk = new short[BUFFER_SAMPLES];

        try {
            while (read < totalSamples && !mCancelled) {
                int n = record.read(chunk, 0, chunk.length);

                if (n < 0) {
                    break;
                }

                System.arraycopy(chunk, 0, all, read, n);
                read += n;
            }
        } catch (Exception ignored) {
            // The recorder stopped out from under us (a call, a device change).
        } finally {
            release(record);
        }

        if (read <= 0) {
            return null;
        }

        if (read == totalSamples) {
            return all;
        }

        short[] trimmed = new short[read];
        System.arraycopy(all, 0, trimmed, 0, read);
        return trimmed;
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
    public void cancel() {
        mCancelled = true;

        if (mRecord != null) {
            release(mRecord);
        }
    }

    @Nullable
    private AudioDeviceInfo deviceForId(AudioDeviceInfo[] devices, int id) {
        for (AudioDeviceInfo device : devices) {
            if (device.getId() == id) {
                return device;
            }
        }
        return null;
    }

    /**
     * The input devices this TV offers, or null when the platform has no way to list them (before
     * API 31): the caller then skips the probe and uses the default source.
     */
    @Nullable
    private AudioDeviceInfo[] inputDevices() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return null;
        }

        AudioManager audio = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);
        if (audio == null) {
            return null;
        }

        List<AudioDeviceInfo> devices = new ArrayList<>();

        for (int type : INPUT_DEVICE_TYPES) {
            for (AudioDeviceInfo device : audio.getDevices(type)) {
                if (device != null && device.isSource() && !devices.contains(device)) {
                    devices.add(device);
                }
            }
        }

        return devices.isEmpty() ? null : devices.toArray(new AudioDeviceInfo[0]);
    }

    private static String deviceLabel(AudioDeviceInfo device, int source) {
        String name = String.valueOf(device.getProductName());

        if (name == null || name.isEmpty()) {
            name = "microphone #" + device.getId();
        }

        return source == RECOGNITION_SOURCE ? name + " (voice)" : name + " (mic)";
    }
}
