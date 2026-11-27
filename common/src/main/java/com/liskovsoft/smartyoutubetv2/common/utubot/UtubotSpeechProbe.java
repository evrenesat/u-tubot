package com.liskovsoft.smartyoutubetv2.common.utubot;

/**
 * Whether a recording heard anything. A TV or remote whose microphone is muted or absent delivers
 * silence; the root-mean-square tells that from speech, so the owner sees "no speech" instead of a
 * transcription of nothing. Pure and unit-tested; the recording loop is in {@link AudioCapture}.
 */
public final class UtubotSpeechProbe {
    /** Below this root-mean-square a recording is treated as silence. */
    static final float USABLE_RMS_FLOOR = 15.0f;

    private UtubotSpeechProbe() {
    }

    /**
     * The root-mean-square of a buffer of 16-bit samples: loudness, which tells speech from a
     * silent microphone. Zero for an empty buffer.
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

    /** True when the recording is loud enough to hold speech. */
    public static boolean isUsable(short[] samples) {
        return measureRms(samples) > USABLE_RMS_FLOOR;
    }
}
