package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * What a film stream's release name says about its picture and sound (codec, bit depth, HDR type, Dolby Vision profile, audio, source), and
 * whether a given TV can show that picture in colour. The name is all an addon gives before the file is opened; the real format is logged
 * from the player at start.
 *
 * <p>Why it matters: a Dolby Vision profile 5 file has no HDR10 base layer. A decoder that does not do Dolby Vision plays it as a green and
 * purple or grey picture. Profiles 7 and 8 carry an HDR10 base layer that a plain HEVC decoder shows correctly.
 */
public final class UtubotFilmFormat {
    public static final int PROFILE_UNKNOWN = 0;
    public static final int PROFILE_5 = 5;
    public static final int PROFILE_7 = 7;
    public static final int PROFILE_8 = 8;

    public enum Codec { UNKNOWN, H264, HEVC, AV1 }

    public enum Hdr { SDR, HDR10, HDR10_PLUS, HLG, DOLBY_VISION }

    /** How well a TV shows the stream, best first; the order is the sort order of the stream list */
    public enum Verdict {
        /** Colour as intended */
        FULL,
        /** Shown in colour, but not as intended (HDR10 layer of Dolby Vision, HDR on a TV that is not HDR, unknown profile) */
        REDUCED,
        /** Wrong or no colour (Dolby Vision profile 5 without a Dolby Vision decoder) or no decoder for the codec */
        NO_COLOUR
    }

    /** What the TV can do; see {@link UtubotFilmDevice} for the real one */
    public interface Device {
        boolean decodes(Codec codec);

        boolean decodesDolbyVision();

        boolean displaysHdr10();
    }

    private static final String B = "(?<![a-z0-9])";
    private static final String E = "(?![a-z0-9])";
    private static final Pattern HEVC = Pattern.compile("(?i)" + B + "(hevc|x\\.?265|h\\.?265)" + E);
    private static final Pattern H264 = Pattern.compile("(?i)" + B + "(avc|x\\.?264|h\\.?264)" + E);
    private static final Pattern AV1 = Pattern.compile("(?i)" + B + "av1" + E);
    private static final Pattern BITS = Pattern.compile("(?i)" + B + "(?:(8|10|12)[ ._-]?bit|hi10p?)" + E);
    private static final Pattern HDR10_PLUS = Pattern.compile("(?i)" + B + "hdr10(?:[ ._-]?plus|\\+)");
    private static final Pattern HDR10 = Pattern.compile("(?i)" + B + "(?:hdr10|hdr)(?![a-z0-9+])");
    private static final Pattern HLG = Pattern.compile("(?i)" + B + "hlg" + E);
    private static final Pattern DV = Pattern.compile("(?i)" + B + "(?:dv|dovi|dolby[ ._-]?vision)" + E + "|dvh[e1][.]\\d\\d");
    private static final Pattern DV_PROFILE = Pattern.compile(
            "(?i)(?:" + B + "(?:dv|dovi|dolby[ ._-]?vision)[ ._-]?(?:profile[ ._-]?|p)(\\d)" + E + "|" + B + "profile[ ._-]?(\\d)" + E + "|dvh[e1][.]0?(\\d))");
    private static final Pattern DV_PROFILE_BARE = Pattern.compile("(?i)" + B + "(?:dv|dovi)[ ._-]?(\\d)" + E);
    private static final Pattern ATMOS = Pattern.compile("(?i)atmos");
    private static final Pattern TRUEHD = Pattern.compile("(?i)true[ ._-]?hd");
    private static final Pattern DTS_HD = Pattern.compile("(?i)" + B + "dts[ ._-]?(?:hd|x)" + E);
    private static final Pattern DTS = Pattern.compile("(?i)" + B + "dts" + E);
    private static final Pattern EAC3 = Pattern.compile("(?i)" + B + "(?:ddp|dd\\+|e[ ._-]?ac[ ._-]?3|dd[ ._-]?plus)");
    private static final Pattern AC3 = Pattern.compile("(?i)" + B + "(?:dd|ac[ ._-]?3|dolby[ ._-]?digital)" + E);
    private static final Pattern AAC = Pattern.compile("(?i)" + B + "aac" + E);
    private static final Pattern CHANNELS = Pattern.compile("(?<![0-9])([257])[ .]([01])(?![0-9])");
    private static final Pattern REMUX = Pattern.compile("(?i)remux");
    private static final Pattern BLURAY = Pattern.compile("(?i)blu[ ._-]?ray|bdrip|brrip|" + B + "bd" + E);
    private static final Pattern WEB = Pattern.compile("(?i)" + B + "web(?:[ ._-]?(?:dl|rip))?" + E);
    private static final Pattern HDTV = Pattern.compile("(?i)hdtv");
    private static final Pattern CAM = Pattern.compile("(?i)" + B + "(?:cam|hdcam|telesync|ts|telecine)" + E);

    public final Codec codec;
    /** 8, 10 or 12; 0 when the name does not say */
    public final int bitDepth;
    public final Hdr hdr;
    /** True when Dolby Vision comes with an HDR10 layer the name mentions (e.g. "DV HDR10") */
    public final boolean hasHdr10Layer;
    /** 5, 7 or 8; {@link #PROFILE_UNKNOWN} when it is not Dolby Vision or the name does not say */
    public final int dolbyVisionProfile;
    public final String audio;
    public final String channels;
    public final String source;

    private UtubotFilmFormat(Codec codec, int bitDepth, Hdr hdr, boolean hasHdr10Layer, int dolbyVisionProfile, String audio, String channels,
                             String source) {
        this.codec = codec;
        this.bitDepth = bitDepth;
        this.hdr = hdr;
        this.hasHdr10Layer = hasHdr10Layer;
        this.dolbyVisionProfile = dolbyVisionProfile;
        this.audio = audio;
        this.channels = channels;
        this.source = source;
    }

    public static UtubotFilmFormat parse(@Nullable String text) {
        String name = text == null ? "" : text;

        Codec codec = HEVC.matcher(name).find() ? Codec.HEVC : AV1.matcher(name).find() ? Codec.AV1 : H264.matcher(name).find() ? Codec.H264 : Codec.UNKNOWN;
        int bits = 0;
        Matcher bitMatcher = BITS.matcher(name);

        if (bitMatcher.find()) {
            bits = bitMatcher.group(1) != null ? Integer.parseInt(bitMatcher.group(1)) : 10;
        }

        boolean dv = DV.matcher(name).find();
        boolean hdr10Plus = HDR10_PLUS.matcher(name).find();
        boolean hdr10 = HDR10.matcher(name).find();
        boolean hlg = HLG.matcher(name).find();
        Hdr hdr = dv ? Hdr.DOLBY_VISION : hdr10Plus ? Hdr.HDR10_PLUS : hdr10 ? Hdr.HDR10 : hlg ? Hdr.HLG : Hdr.SDR;

        if (hdr != Hdr.SDR && bits == 0) {
            bits = 10; // HDR is always 10 bit or more
        }

        return new UtubotFilmFormat(codec, bits, hdr, dv && (hdr10 || hdr10Plus), dv ? dolbyVisionProfile(name) : PROFILE_UNKNOWN,
                audio(name), channels(name), source(name));
    }

    private static int dolbyVisionProfile(String name) {
        Matcher matcher = DV_PROFILE.matcher(name);

        if (!matcher.find()) {
            matcher = DV_PROFILE_BARE.matcher(name);

            if (!matcher.find()) {
                return PROFILE_UNKNOWN;
            }
        }

        for (int i = 1; i <= matcher.groupCount(); i++) {
            if (matcher.group(i) != null) {
                int profile = Integer.parseInt(matcher.group(i));

                return profile == PROFILE_5 || profile == PROFILE_7 || profile == PROFILE_8 ? profile : PROFILE_UNKNOWN;
            }
        }

        return PROFILE_UNKNOWN;
    }

    private static String audio(String name) {
        if (ATMOS.matcher(name).find()) {
            return "Atmos";
        } else if (TRUEHD.matcher(name).find()) {
            return "TrueHD";
        } else if (DTS_HD.matcher(name).find()) {
            return "DTS-HD";
        } else if (DTS.matcher(name).find()) {
            return "DTS";
        } else if (EAC3.matcher(name).find()) {
            return "DD+";
        } else if (AC3.matcher(name).find()) {
            return "DD";
        } else if (AAC.matcher(name).find()) {
            return "AAC";
        }

        return "";
    }

    private static String channels(String name) {
        Matcher matcher = CHANNELS.matcher(name);

        return matcher.find() ? matcher.group(1) + "." + matcher.group(2) : "";
    }

    private static String source(String name) {
        if (REMUX.matcher(name).find()) {
            return "Remux";
        } else if (BLURAY.matcher(name).find()) {
            return "Blu-ray";
        } else if (WEB.matcher(name).find()) {
            return "WEB";
        } else if (HDTV.matcher(name).find()) {
            return "HDTV";
        } else if (CAM.matcher(name).find()) {
            return "Cam";
        }

        return "";
    }

    /**
     * How well this TV shows the stream. Profile 5 has no HDR10 layer, so without a Dolby Vision decoder it cannot be shown in colour. Other
     * Dolby Vision is shown from its HDR10 layer (reduced); HDR on a TV that is not HDR is reduced too.
     */
    public Verdict verdict(Device device) {
        if (codec != Codec.UNKNOWN && !device.decodes(codec)) {
            return Verdict.NO_COLOUR;
        }

        if (hdr == Hdr.DOLBY_VISION && !device.decodesDolbyVision()) {
            return dolbyVisionProfile == PROFILE_5 ? Verdict.NO_COLOUR : Verdict.REDUCED;
        }

        if ((hdr == Hdr.HDR10 || hdr == Hdr.HDR10_PLUS || hdr == Hdr.HLG) && !device.displaysHdr10()) {
            return Verdict.REDUCED;
        }

        return Verdict.FULL;
    }

    /**
     * Why the stream is not {@link Verdict#FULL} on this TV, as a short note for the list; empty when it is full.
     */
    public String note(Device device) {
        if (codec != Codec.UNKNOWN && !device.decodes(codec)) {
            return "This TV cannot decode " + codecLabel();
        }

        if (hdr == Hdr.DOLBY_VISION && !device.decodesDolbyVision()) {
            if (dolbyVisionProfile == PROFILE_5) {
                return "Dolby Vision 5: wrong colours on this TV";
            }

            return hasHdr10Layer || dolbyVisionProfile == PROFILE_7 || dolbyVisionProfile == PROFILE_8
                    ? "Plays as HDR10 on this TV" : "Dolby Vision, profile unknown";
        }

        return verdict(device) == Verdict.REDUCED ? "This TV is not HDR" : "";
    }

    public String codecLabel() {
        switch (codec) {
            case HEVC:
                return "HEVC";
            case H264:
                return "H.264";
            case AV1:
                return "AV1";
            default:
                return "";
        }
    }

    public String hdrLabel() {
        switch (hdr) {
            case DOLBY_VISION:
                return dolbyVisionProfile == PROFILE_UNKNOWN ? "Dolby Vision" : "Dolby Vision P" + dolbyVisionProfile;
            case HDR10_PLUS:
                return "HDR10+";
            case HDR10:
                return "HDR10";
            case HLG:
                return "HLG";
            default:
                return "";
        }
    }

    /**
     * The format as chips for the list: codec, bit depth, HDR, audio, channels, source (empty ones left out).
     */
    public List<String> chips() {
        List<String> chips = new ArrayList<>();

        addIfSet(chips, codecLabel());

        if (bitDepth > 8) {
            chips.add(bitDepth + "-bit");
        }

        addIfSet(chips, hdrLabel());

        if (hasHdr10Layer && hdr == Hdr.DOLBY_VISION) {
            chips.add("HDR10");
        }

        addIfSet(chips, audio);
        addIfSet(chips, channels);
        addIfSet(chips, source);

        return chips;
    }

    /** One line for the log; never holds an address */
    public String describe() {
        return String.format(Locale.US, "codec=%s bits=%d hdr=%s dvProfile=%d hdr10Layer=%s", codec, bitDepth, hdr, dolbyVisionProfile, hasHdr10Layer);
    }

    private static void addIfSet(List<String> chips, String chip) {
        if (!chip.isEmpty()) {
            chips.add(chip);
        }
    }
}
