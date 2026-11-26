package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * The WAV muxer the recorder's PCM goes through before the upload: a RIFF/WAVE container Whisper
 * opens, with the 16-bit little-endian samples the recorder already produces.
 */
public class UtubotWavTest {
    @Test
    public void theHeaderIsARiffWaveContainer() {
        byte[] wav = UtubotWav.encode(new short[]{1, 2, 3}, 16_000, 1);

        assertTrue(new String(wav, 0, 4, StandardCharsets.US_ASCII).equals("RIFF"));
        assertTrue(new String(wav, 8, 4, StandardCharsets.US_ASCII).equals("WAVE"));
        assertTrue(new String(wav, 12, 4, StandardCharsets.US_ASCII).equals("fmt "));
        assertTrue(new String(wav, 36, 4, StandardCharsets.US_ASCII).equals("data"));
    }

    @Test
    public void theFmtChunkIsPcmForTheGivenChannelsAndRate() {
        ByteBuffer header = ByteBuffer.wrap(UtubotWav.encode(new short[0], 16_000, 2)).order(ByteOrder.LITTLE_ENDIAN);

        header.position(20);
        assertEquals((short) 1, header.getShort()); // PCM format type
        assertEquals((short) 2, header.getShort()); // channels
        assertEquals(16_000, header.getInt()); // sample rate
        assertEquals(16_000 * 2 * 2, header.getInt()); // byte rate = rate * channels * bytes per sample (16-bit = 2 bytes)
        assertEquals((short) 4, header.getShort()); // block align = channels * bytes per sample
        assertEquals((short) 16, header.getShort()); // bits per sample
    }

    @Test
    public void theDataChunkReportsTheSampleCount() {
        short[] samples = {5, -5, 100, -100};
        byte[] wav = UtubotWav.encode(samples, 16_000, 1);
        ByteBuffer header = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN);

        header.position(40);
        assertEquals(samples.length * 2, header.getInt()); // data size in bytes
        assertEquals(wav.length, 44 + samples.length * 2); // nothing but the header and the samples
    }

    @Test
    public void theSamplesAreTheLittleEndianTwoBytesEach() {
        short[] samples = {0x0102, 0x0304, (short) 0xFFFF};
        ByteBuffer data = ByteBuffer.wrap(UtubotWav.encode(samples, 16_000, 1)).order(ByteOrder.LITTLE_ENDIAN);

        data.position(44);

        for (short sample : samples) {
            assertEquals(sample, data.getShort());
        }
    }

    @Test
    public void emptySamplesAreJustTheHeader() {
        byte[] wav = UtubotWav.encode(new short[0], 8_000, 1);

        assertEquals(44, wav.length);
        ByteBuffer header = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN);

        header.position(4);
        assertEquals(36, header.getInt()); // the RIFF size = WAVE + fmt + data headers, no samples
        header.position(40);
        assertEquals(0, header.getInt()); // no data
    }

    @Test
    public void stereoInterleavesTheChannels() {
        short[] left = {1, 3};
        short[] right = {2, 4};
        short[] interleaved = new short[left.length * 2];

        for (int i = 0; i < left.length; i++) {
            interleaved[i * 2] = left[i];
            interleaved[i * 2 + 1] = right[i];
        }

        ByteBuffer data = ByteBuffer.wrap(UtubotWav.encode(interleaved, 16_000, 2)).order(ByteOrder.LITTLE_ENDIAN);

        data.position(44);
        assertArrayEquals(interleaved, new short[]{data.getShort(), data.getShort(), data.getShort(), data.getShort()});
    }
}
