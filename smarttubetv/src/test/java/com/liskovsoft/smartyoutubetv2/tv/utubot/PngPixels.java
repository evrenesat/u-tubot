package com.liskovsoft.smartyoutubetv2.tv.utubot;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

/**
 * The pixels of an 8-bit RGBA PNG without interlacing (what the Settings icons are). The unit tests run without the Android graphics
 * stack and the Android build has no java.desktop, so the few bytes of the format are read here.
 */
final class PngPixels {
    private static final byte[] SIGNATURE = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    private static final int CHUNK_OVERHEAD = 12;
    private static final int COLOR_TYPE_RGBA = 6;
    private static final int BYTES_PER_PIXEL = 4;
    private static final int OPAQUE_MASK = 0xFF;

    final int width;
    final int height;
    /** red, green, blue, alpha of each pixel, row by row */
    private final byte[] mPixels;

    private PngPixels(int width, int height, byte[] pixels) {
        this.width = width;
        this.height = height;
        mPixels = pixels;
    }

    static PngPixels read(Path file) throws IOException {
        ByteBuffer data = ByteBuffer.wrap(Files.readAllBytes(file));

        for (byte expected : SIGNATURE) {
            if (data.get() != expected) {
                throw new IOException(file + " is not a PNG");
            }
        }

        int width = 0;
        int height = 0;
        ByteArrayOutputStream compressed = new ByteArrayOutputStream();

        while (data.remaining() >= CHUNK_OVERHEAD) {
            int length = data.getInt();
            byte[] type = new byte[4];
            data.get(type);
            String name = new String(type, java.nio.charset.StandardCharsets.US_ASCII);
            byte[] body = new byte[length];
            data.get(body);
            data.getInt(); // checksum

            if (name.equals("IHDR")) {
                ByteBuffer header = ByteBuffer.wrap(body);
                width = header.getInt();
                height = header.getInt();
                boolean isRgba8 = header.get() == 8 && header.get() == COLOR_TYPE_RGBA;
                boolean isPlain = header.get() == 0 && header.get() == 0 && header.get() == 0;

                if (!isRgba8 || !isPlain) {
                    throw new IOException(file + " is not an 8-bit RGBA PNG without interlacing");
                }
            } else if (name.equals("IDAT")) {
                compressed.write(body);
            }
        }

        return new PngPixels(width, height, unfilter(inflate(compressed.toByteArray(), height * (1 + width * BYTES_PER_PIXEL)), width, height));
    }

    private static byte[] inflate(byte[] compressed, int expected) throws IOException {
        Inflater inflater = new Inflater();
        inflater.setInput(compressed);
        byte[] raw = new byte[expected];

        try {
            int total = 0;

            while (total < expected && !inflater.finished()) {
                total += inflater.inflate(raw, total, expected - total);
            }

            if (total != expected) {
                throw new IOException("the image data is " + total + " bytes, expected " + expected);
            }
        } catch (DataFormatException e) {
            throw new IOException(e);
        } finally {
            inflater.end();
        }

        return raw;
    }

    /**
     * Undoes the per-row filters (none, sub, up, average, Paeth)
     */
    private static byte[] unfilter(byte[] raw, int width, int height) throws IOException {
        int stride = width * BYTES_PER_PIXEL;
        byte[] pixels = new byte[stride * height];

        for (int y = 0; y < height; y++) {
            int filter = raw[y * (stride + 1)];
            int source = y * (stride + 1) + 1;
            int target = y * stride;

            for (int i = 0; i < stride; i++) {
                int left = i >= BYTES_PER_PIXEL ? pixels[target + i - BYTES_PER_PIXEL] & OPAQUE_MASK : 0;
                int up = y > 0 ? pixels[target - stride + i] & OPAQUE_MASK : 0;
                int upLeft = y > 0 && i >= BYTES_PER_PIXEL ? pixels[target - stride + i - BYTES_PER_PIXEL] & OPAQUE_MASK : 0;
                int predicted;

                switch (filter) {
                    case 0:
                        predicted = 0;
                        break;
                    case 1:
                        predicted = left;
                        break;
                    case 2:
                        predicted = up;
                        break;
                    case 3:
                        predicted = (left + up) / 2;
                        break;
                    case 4:
                        predicted = paeth(left, up, upLeft);
                        break;
                    default:
                        throw new IOException("unknown filter " + filter);
                }

                pixels[target + i] = (byte) ((raw[source + i] & OPAQUE_MASK) + predicted);
            }
        }

        return pixels;
    }

    private static int paeth(int left, int up, int upLeft) {
        int estimate = left + up - upLeft;
        int distanceLeft = Math.abs(estimate - left);
        int distanceUp = Math.abs(estimate - up);
        int distanceUpLeft = Math.abs(estimate - upLeft);

        if (distanceLeft <= distanceUp && distanceLeft <= distanceUpLeft) {
            return left;
        }

        return distanceUp <= distanceUpLeft ? up : upLeft;
    }

    int alpha(int x, int y) {
        return mPixels[(y * width + x) * BYTES_PER_PIXEL + 3] & OPAQUE_MASK;
    }

    /**
     * @return red, green and blue of the pixel as 0xRRGGBB
     */
    int rgb(int x, int y) {
        int offset = (y * width + x) * BYTES_PER_PIXEL;

        return ((mPixels[offset] & OPAQUE_MASK) << 16) | ((mPixels[offset + 1] & OPAQUE_MASK) << 8) | (mPixels[offset + 2] & OPAQUE_MASK);
    }

    /**
     * @return left, top, right, bottom (exclusive) of the pixels that are not fully transparent
     */
    int[] visibleBounds() {
        int left = width;
        int top = height;
        int right = 0;
        int bottom = 0;

        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                if (alpha(x, y) != 0) {
                    left = Math.min(left, x);
                    top = Math.min(top, y);
                    right = Math.max(right, x + 1);
                    bottom = Math.max(bottom, y + 1);
                }
            }
        }

        return new int[]{left, top, right, bottom};
    }
}
