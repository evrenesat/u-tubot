package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import java.util.Arrays;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * Whether a recording is loud enough to hold speech. The recording loop is in {@link AudioCapture}.
 */
public class UtubotSpeechProbeTest {
    private static short[] constant(int value) {
        short[] samples = new short[100];
        Arrays.fill(samples, (short) value);
        return samples;
    }

    @Test
    public void anEmptyOrNullRecordingHasNoLoudness() {
        assertEquals(0.0f, UtubotSpeechProbe.measureRms(new short[0]), 0.0001f);
        assertEquals(0.0f, UtubotSpeechProbe.measureRms(null), 0.0001f);
    }

    @Test
    public void aConstantRecordingIsLoudAsItsMagnitude() {
        assertEquals(100.0f, UtubotSpeechProbe.measureRms(constant(100)), 0.0001f);
        assertEquals(100.0f, UtubotSpeechProbe.measureRms(constant(-100)), 0.0001f);
    }

    @Test
    public void silenceIsNotUsableAndSpeechIs() {
        assertFalse(UtubotSpeechProbe.isUsable(null));
        assertFalse(UtubotSpeechProbe.isUsable(new short[0]));
        assertFalse(UtubotSpeechProbe.isUsable(constant(0)));
        assertFalse(UtubotSpeechProbe.isUsable(constant((int) UtubotSpeechProbe.USABLE_RMS_FLOOR)));
        assertTrue(UtubotSpeechProbe.isUsable(constant((int) UtubotSpeechProbe.USABLE_RMS_FLOOR + 1)));
    }
}
