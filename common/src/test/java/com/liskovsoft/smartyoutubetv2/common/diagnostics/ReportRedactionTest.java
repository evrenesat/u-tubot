package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class ReportRedactionTest {
    private static final String RD_TOKEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345";

    @Test
    public void aRealDebridTokenInTheAddonPathIsMasked() {
        String text = "open https://addon.example/realdebrid=" + RD_TOKEN + "/stream/movie/tt1.json failed";

        String result = ReportRedaction.redact(text);

        assertFalse(result, result.contains(RD_TOKEN));
        assertTrue(result, result.contains("https://addon.example/" + ReportRedaction.MASK + "/stream/movie/tt1.json"));
    }

    @Test
    public void theQueryAndTheOpaqueKeyOfADirectLinkAreMasked() {
        String result = ReportRedaction.redact("GET https://cdn.example.net/d/QWERTYUIOPASDFGHJKLZXCV/Movie.2160p.mkv?token=abc123&x=1 error");

        assertEquals("GET https://cdn.example.net/d/" + ReportRedaction.MASK + "/Movie.2160p.mkv?" + ReportRedaction.MASK + " error", result);
    }

    @Test
    public void userInfoOfAnAddressGoes() {
        assertEquals("https://host.example/path", ReportRedaction.redact("https://user:pass@host.example/path"));
    }

    @Test
    public void namedSecretsBearerAndDeviceTokensAreMasked() {
        String result = ReportRedaction.redact("api_key=SECRET1 Authorization: Bearer abc.def-ghi device utb_deadbeef password=hunter22");

        assertFalse(result, result.contains("SECRET1"));
        assertFalse(result, result.contains("abc.def-ghi"));
        assertFalse(result, result.contains("utb_deadbeef"));
        assertFalse(result, result.contains("hunter22"));
    }

    @Test
    public void exactSecretsAreMaskedWhereverTheyAppear() {
        String result = ReportRedaction.redact("the token " + RD_TOKEN + " leaked in a title", RD_TOKEN, "x");

        assertEquals("the token " + ReportRedaction.MASK + " leaked in a title", result);
    }

    @Test
    public void ordinaryTextIsLeftAlone() {
        String text = "player.state READY play at 1200 codec=H264 size=1920x1080 http://10.0.2.2:18791/media/film.mkv";

        assertEquals(text, ReportRedaction.redact(text));
    }
}
