package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * The recording's upload through the backend's speech-to-text (`POST /v1/speech`): the WAV is a named
 * multipart file part, the text comes back, and a rejected upload surfaces the backend's own reason.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSpeechClientTest {
    private static final String TOKEN = "secret-token";
    private static final String TEXT = "Keep the intro, cut the ad break.";
    private static final String LANGUAGE = "pt-BR";
    private TinyHttpServer mServer;
    private final java.util.concurrent.atomic.AtomicReference<String> mAuth = new java.util.concurrent.atomic.AtomicReference<>();
    private final java.util.concurrent.atomic.AtomicReference<String> mBody = new java.util.concurrent.atomic.AtomicReference<>();
    private final java.util.concurrent.atomic.AtomicReference<String> mMethod = new java.util.concurrent.atomic.AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/speech", request -> {
            mMethod.set(request.method);
            mAuth.set(request.headers.get("authorization"));
            mBody.set(request.body);
            return new TinyHttpServer.Response(200, "{\"text\":\"" + TEXT + "\"}");
        });
    }

    @After
    public void stop() {
        mServer.stop();
    }

    private String base() {
        return "http://127.0.0.1:" + mServer.getPort() + "/";
    }

    private byte[] recording() {
        return UtubotWav.encode(new short[]{1, -1, 2, -2, 3}, 16_000, 1);
    }

    @Test
    public void itUploadsTheRecordingAsANamedFileAndReturnsTheText() throws IOException {
        String text = new UtubotClient(base(), TOKEN).speech(recording(), "recording.wav", "audio/wav", null);

        assertEquals(TEXT, text);
        assertEquals("POST", mMethod.get());
        assertEquals("Bearer " + TOKEN, mAuth.get());
        // The audio is uploaded as a named file part, so the STT server can pick a decoder.
        assertTrue(mBody.get().contains("filename=\"recording.wav\""));
    }

    @Test
    public void itSendsTheLanguageHintWhenSet() throws IOException {
        new UtubotClient(base(), TOKEN).speech(recording(), "recording.wav", "audio/wav", LANGUAGE);

        assertTrue(mBody.get().contains("name=\"language\""));
        assertTrue(mBody.get().contains(LANGUAGE));
    }

    @Test
    public void itOmitsTheLanguageHintWhenNull() throws IOException {
        new UtubotClient(base(), TOKEN).speech(recording(), "recording.wav", "audio/wav", null);

        assertTrue(mBody.get().contains("filename=\"recording.wav\""));
        assertTrue(!mBody.get().contains("name=\"language\""));
    }

    @Test
    public void itOmitsTheLanguageHintWhenEmpty() throws IOException {
        new UtubotClient(base(), TOKEN).speech(recording(), "recording.wav", "audio/wav", "");

        assertTrue(!mBody.get().contains("name=\"language\""));
    }

    @Test
    public void itThrowsWhenTheBackendRejectsTheRecording() {
        mServer.on("/v1/speech", request -> new TinyHttpServer.Response(413,
                "{\"error\":\"Recording too long, 60s over the 50s limit.\"}"));

        try {
            new UtubotClient(base(), TOKEN).speech(recording(), "recording.wav", "audio/wav", null);
            fail("Expected an IOException for the rejected upload");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("60s over the 50s limit"));
        }
    }

    @Test
    public void itThrowsOnANonJsonResponse() {
        mServer.on("/v1/speech", request -> new TinyHttpServer.Response(200, "not json"));

        try {
            new UtubotClient(base(), TOKEN).speech(recording(), "recording.wav", "audio/wav", null);
            fail("Expected an IOException for the non-JSON response");
        } catch (IOException expected) {
            assertNotNull(expected.getMessage());
        }
    }
}
