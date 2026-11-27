package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

/**
 * A minimal RIFF/WAVE muxer for the 16-bit PCM the TV's {@code AudioRecord} reads, so the backend's
 * speech-to-text gets a file Whisper accepts instead of raw samples (a raw PCM blob has no container
 * for the decoder to open).
 */
public final class UtubotWav {
    private static final int BYTES_PER_SAMPLE = 16 / 8;

    private UtubotWav() {
    }

    /**
     * @param samples the little-endian 16-bit samples, interleaved per channel
     * @param sampleRate the samples per second per channel
     * @param channels the interleaved channels (1 = mono)
     * @return a RIFF/WAVE PCM file the STT server can read
     */
    public static byte[] encode(short[] samples, int sampleRate, int channels) {
        int dataBytes = samples.length * channels * BYTES_PER_SAMPLE;
        int byteRate = sampleRate * channels * BYTES_PER_SAMPLE;

        ByteArrayOutputStream out = new ByteArrayOutputStream(44 + dataBytes);
        write(out, "RIFF".getBytes(StandardCharsets.US_ASCII));
        writeInt(out, 36 + dataBytes);
        write(out, "WAVE".getBytes(StandardCharsets.US_ASCII));

        write(out, "fmt ".getBytes(StandardCharsets.US_ASCII));
        writeInt(out, 16); // fmt chunk size for PCM
        writeShort(out, (short) 1); // PCM format type
        writeShort(out, (short) channels);
        writeInt(out, sampleRate);
        writeInt(out, byteRate);
        writeShort(out, (short) (channels * BYTES_PER_SAMPLE)); // block align
        writeShort(out, (short) 16); // bits per sample

        write(out, "data".getBytes(StandardCharsets.US_ASCII));
        writeInt(out, dataBytes);

        ByteBuffer little = ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN);
        for (short sample : samples) {
            little.clear();
            little.putShort(sample);
            out.write(little.array(), 0, 2);
        }

        return out.toByteArray();
    }

    private static void write(ByteArrayOutputStream out, byte[] bytes) {
        out.write(bytes, 0, bytes.length);
    }

    private static void writeInt(ByteArrayOutputStream out, int value) {
        out.write(value & 0xFF);
        out.write((value >> 8) & 0xFF);
        out.write((value >> 16) & 0xFF);
        out.write((value >> 24) & 0xFF);
    }

    private static void writeShort(ByteArrayOutputStream out, short value) {
        out.write(value & 0xFF);
        out.write((value >> 8) & 0xFF);
    }
}
