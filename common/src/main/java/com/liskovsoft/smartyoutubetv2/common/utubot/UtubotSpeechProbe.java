package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.util.List;

/**
 * Picking the TV's microphone. The remote's mic button usually goes to the system assistant, and
 * raw capture from the remote is device-dependent, so the owner probes each {@code AudioManager}
 * input device (VOICE_RECOGNITION / MIC sources, {@code setPreferredDevice}) and records a few
 * seconds from each to see which one delivers usable audio; this picks the best of them. The
 * selection is pure and unit-tested; the recording loop is in {@link UtubotSpeechInput}.
 */
public final class UtubotSpeechProbe {
    /** Below this root-mean-square a recording is treated as silence: no usable audio from the device. */
    static final float USABLE_RMS_FLOOR = 15.0f;

    private UtubotSpeechProbe() {
    }

    /**
     * The root-mean-square of a buffer of 16-bit samples: loudness, which tells a device that
     * hears speech from one that only hears the room. Zero for an empty buffer.
     */
    public static float measureRms(short[] samples) {
        if (samples == null || samples.length == 0) {
            return 0.0f;
        }

        double sum = 0.0;

        for (short sample : samples) {
            double value = sample;
            sum += value * value;
        }

        return (float) Math.sqrt(sum / samples.length);
    }

    /**
     * The index of the reading with the highest usable loudness, or -1 when none is above the
     * silence floor (so the caller falls back to the platform recogniser).
     */
    public static int selectBest(List<SpeechDeviceReading> readings) {
        int best = -1;
        float bestRms = USABLE_RMS_FLOOR;

        for (int i = 0; i < readings.size(); i++) {
            float rms = readings.get(i).rms;

            if (rms > bestRms) {
                bestRms = rms;
                best = i;
            }
        }

        return best;
    }

    /** One input device's probe: which device, which recording source, and how loud it was. */
    public static final class SpeechDeviceReading {
        public final int deviceId;
        public final String deviceName;
        public final int source;
        public final float rms;

        public SpeechDeviceReading(int deviceId, String deviceName, int source, float rms) {
            this.deviceId = deviceId;
            this.deviceName = deviceName;
            this.source = source;
            this.rms = rms;
        }
    }
}
