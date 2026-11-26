package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * The pure microphone selection: which probe is loud enough to be speech, and which of them is the
 * best. The recording loop that fills the probes is in {@link UtubotSpeechInput} and {@link AudioCapture}.
 */
public class UtubotSpeechProbeTest {
    private UtubotSpeechProbe.SpeechDeviceReading reading(int deviceId, String name, int source, float rms) {
        return new UtubotSpeechProbe.SpeechDeviceReading(deviceId, name, source, rms);
    }

    @Test
    public void anEmptyOrNullRecordingHasNoLoudness() {
        assertEquals(0.0f, UtubotSpeechProbe.measureRms(new short[0]), 0.0001f);
        assertEquals(0.0f, UtubotSpeechProbe.measureRms(null), 0.0001f);
    }

    @Test
    public void aConstantRecordingIsLoudAsItsMagnitude() {
        short[] samples = new short[100];
        Arrays.fill(samples, (short) 100);

        assertEquals(100.0f, UtubotSpeechProbe.measureRms(samples), 0.0001f);
    }

    @Test
    public void theLoudestUsableProbeIsChosen() {
        List<UtubotSpeechProbe.SpeechDeviceReading> probes = Arrays.asList(
                reading(1, "room mic", 0, 4.0f),
                reading(2, "headset", 1, 42.0f),
                reading(3, "builtin", 0, 20.0f));

        assertEquals(1, UtubotSpeechProbe.selectBest(probes));
    }

    @Test
    public void aProbeBelowTheSilenceFloorIsNotUsable() {
        List<UtubotSpeechProbe.SpeechDeviceReading> probes = Arrays.asList(
                reading(1, "room mic", 0, 4.0f),
                reading(2, "headset", 1, 10.0f));

        assertEquals(-1, UtubotSpeechProbe.selectBest(probes));
    }

    @Test
    public void theFloorIsInclusiveOfTheExactEdge() {
        List<UtubotSpeechProbe.SpeechDeviceReading> probes = Arrays.asList(
                reading(1, "quiet", 0, 10.0f),
                reading(2, "just enough", 1, 15.0f + 0.001f));

        assertEquals(1, UtubotSpeechProbe.selectBest(probes));
    }

    @Test
    public void noProbesMeansNoUsableMicrophone() {
        assertEquals(-1, UtubotSpeechProbe.selectBest(new ArrayList<>()));
    }

    @Test
    public void theChosenReadingIsTheLoudestOne() {
        List<UtubotSpeechProbe.SpeechDeviceReading> probes = Arrays.asList(
                reading(1, "room mic", 0, 4.0f),
                reading(2, "headset", 1, 42.0f));

        UtubotSpeechProbe.SpeechDeviceReading chosen = probes.get(UtubotSpeechProbe.selectBest(probes));

        assertEquals(2, chosen.deviceId);
        assertEquals("headset", chosen.deviceName);
        assertTrue(chosen.rms > UtubotSpeechProbe.USABLE_RMS_FLOOR);
    }
}
