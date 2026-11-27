package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmFormat.Codec;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmFormat.Hdr;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmFormat.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient.Stream;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotFilmFormatTest {
    private static UtubotFilmFormat.Device device(boolean dv, boolean hdr, Codec... codecs) {
        return new UtubotFilmFormat.Device() {
            @Override
            public boolean decodes(Codec codec) {
                return Arrays.asList(codecs).contains(codec);
            }

            @Override
            public boolean decodesDolbyVision() {
                return dv;
            }

            @Override
            public boolean displaysHdr10() {
                return hdr;
            }
        };
    }

    private static final UtubotFilmFormat.Device PLAIN_HDR_TV = device(false, true, Codec.HEVC, Codec.H264);
    private static final UtubotFilmFormat.Device DV_TV = device(true, true, Codec.HEVC, Codec.H264);

    @Test
    public void parsesATorrentioTitle() {
        UtubotFilmFormat f = UtubotFilmFormat.parse("Torrentio 4k Movie.2024.2160p.UHD.BluRay.REMUX.HEVC.HDR10+.TrueHD.7.1.Atmos-GRP");

        assertEquals(Codec.HEVC, f.codec);
        assertEquals(Hdr.HDR10_PLUS, f.hdr);
        assertEquals(10, f.bitDepth);
        assertEquals("Atmos", f.audio);
        assertEquals("7.1", f.channels);
        assertEquals("Remux", f.source);
    }

    @Test
    public void parsesPlainSdrH264() {
        UtubotFilmFormat f = UtubotFilmFormat.parse("Movie 2010 1080p WEB-DL DDP5.1 x264");

        assertEquals(Codec.H264, f.codec);
        assertEquals(Hdr.SDR, f.hdr);
        assertEquals(0, f.bitDepth);
        assertEquals("DD+", f.audio);
        assertEquals("WEB", f.source);
        assertEquals(Arrays.asList("H.264", "DD+", "5.1", "WEB"), f.chips());
    }

    @Test
    public void tenBitIsReadFromTheName() {
        assertEquals(10, UtubotFilmFormat.parse("Movie 1080p BluRay x265 10bit").bitDepth);
        assertEquals(10, UtubotFilmFormat.parse("Movie 1080p BluRay x265 10-bit").bitDepth);
        assertEquals(10, UtubotFilmFormat.parse("Movie Hi10P").bitDepth);
        assertEquals(8, UtubotFilmFormat.parse("Movie 8bit").bitDepth);
    }

    @Test
    public void dolbyVisionProfilesAreRead() {
        assertEquals(5, UtubotFilmFormat.parse("Movie.2160p.WEB-DL.DV.P5.HEVC").dolbyVisionProfile);
        assertEquals(8, UtubotFilmFormat.parse("Movie 2160p DoVi Profile 8 HDR10").dolbyVisionProfile);
        assertEquals(7, UtubotFilmFormat.parse("Movie 2160p Dolby Vision P7 FEL").dolbyVisionProfile);
        assertEquals(8, UtubotFilmFormat.parse("Movie dvhe.08.06 hevc").dolbyVisionProfile);
        assertEquals(UtubotFilmFormat.PROFILE_UNKNOWN, UtubotFilmFormat.parse("Movie 2160p DV HDR HEVC").dolbyVisionProfile);
        assertEquals(Hdr.DOLBY_VISION, UtubotFilmFormat.parse("Movie 2160p DV HDR HEVC").hdr);
        assertTrue(UtubotFilmFormat.parse("Movie 2160p DV HDR HEVC").hasHdr10Layer);
    }

    @Test
    public void dolbyVisionProfile5NeverGetsAnHdr10Chip() {
        UtubotFilmFormat f = UtubotFilmFormat.parse("Torrentio 4k DV | HDR Movie.2160p.REMUX.HEVC.DV.P5.TrueHD");

        assertEquals(5, f.dolbyVisionProfile);
        assertFalse(f.hasHdr10Layer);
        assertFalse(f.chips().contains("HDR10"));
        assertTrue(UtubotFilmFormat.parse("Movie 2160p DV HDR HEVC").chips().contains("HDR10"));
    }

    @Test
    public void wordsThatMerelyContainDvOrHdrAreNotHdr() {
        assertEquals(Hdr.SDR, UtubotFilmFormat.parse("Advent.2010.1080p.WEB").hdr);
        assertEquals(Hdr.SDR, UtubotFilmFormat.parse("Movie.1080p.Hdrip").hdr);
    }

    @Test
    public void hdr10AloneAndHlgAreRecognised() {
        assertEquals(Hdr.HDR10, UtubotFilmFormat.parse("Movie 2160p HDR").hdr);
        assertEquals(Hdr.HDR10, UtubotFilmFormat.parse("Movie 2160p HDR10 x265").hdr);
        assertEquals(Hdr.HLG, UtubotFilmFormat.parse("Movie 2160p HLG").hdr);
    }

    @Test
    public void dolbyVisionProfile5IsNotShownInColourWithoutADolbyVisionDecoder() {
        UtubotFilmFormat f = UtubotFilmFormat.parse("Movie.2160p.WEB-DL.DV.P5.HEVC");

        assertEquals(Verdict.NO_COLOUR, f.verdict(PLAIN_HDR_TV));
        assertEquals(Verdict.FULL, f.verdict(DV_TV));
        assertEquals("Dolby Vision 5: wrong colours on this TV", f.note(PLAIN_HDR_TV));
    }

    @Test
    public void dolbyVisionProfile8PlaysAsHdr10WithoutADolbyVisionDecoder() {
        UtubotFilmFormat f = UtubotFilmFormat.parse("Movie 2160p DoVi P8 HDR10 HEVC");

        assertEquals(Verdict.REDUCED, f.verdict(PLAIN_HDR_TV));
        assertEquals("Plays as HDR10 on this TV", f.note(PLAIN_HDR_TV));
    }

    @Test
    public void hdrOnATvThatIsNotHdrIsReducedAndMissingDecodersAreNotColour() {
        UtubotFilmFormat hdr = UtubotFilmFormat.parse("Movie 2160p HDR10 HEVC");

        assertEquals(Verdict.REDUCED, hdr.verdict(device(false, false, Codec.HEVC)));
        assertEquals(Verdict.NO_COLOUR, hdr.verdict(device(false, true, Codec.H264)));
        assertEquals(Verdict.FULL, UtubotFilmFormat.parse("Movie 1080p x264").verdict(device(false, false, Codec.H264)));
    }

    @Test
    public void streamsThisTvCannotShowInColourSortLast() {
        Stream dv5 = new Stream("Movie 2160p WEB-DL DV P5 HEVC", "https://h/1", 2160, 30_000_000_000L);
        Stream hdr = new Stream("Movie 2160p HDR10 HEVC", "https://h/2", 2160, 20_000_000_000L);
        Stream hd = new Stream("Movie 1080p x264", "https://h/3", 1080, 5_000_000_000L);
        Stream dv8 = new Stream("Movie 2160p DV P8 HDR10 HEVC", "https://h/4", 2160, 25_000_000_000L);

        List<Stream> sorted = UtubotRealDebridClient.sortedFor(Arrays.asList(dv5, hdr, hd, dv8), PLAIN_HDR_TV);

        assertEquals(Arrays.asList(hdr, hd, dv8, dv5), sorted);
        assertEquals(Arrays.asList(dv5, dv8, hdr, hd), UtubotRealDebridClient.sortedFor(Arrays.asList(hd, hdr, dv8, dv5), DV_TV));
    }
}
