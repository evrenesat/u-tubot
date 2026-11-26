package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.mediaserviceinterfaces.data.MediaSubtitle;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotClientCaptions.Pick;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ClientCaptionTrack;

import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotClientCaptionsTest {
    private static final String BASE = "https://www.youtube.com/api/timedtext?v=abc&lang=%s";
    private static final String TOKEN = "secret-token";

    @Before
    public void reset() {
        UtubotClientCaptions.forgetAll();
    }

    private static MediaSubtitle track(String lang, String type, String suffix) {
        return new MediaSubtitle() {
            @Override public String getBaseUrl() { return String.format(BASE, lang) + suffix; }
            @Override public boolean isTranslatable() { return true; }
            @Override public String getLanguageCode() { return lang; }
            @Override public String getVssId() { return ("asr".equals(type) ? "a." : ".") + lang; }
            @Override public String getName() { return lang + " name"; }
            @Override public String getMimeType() { return null; }
            @Override public String getCodecs() { return null; }
            @Override public String getType() { return type; }
        };
    }

    @Test
    public void picksTheOriginalAutomaticTrackAndTheUsersLanguageOnly() {
        List<MediaSubtitle> all = Arrays.asList(
                track("de", "asr", ""), track("de", "asr", "&tlang=en"), track("en", null, ""), track("fr", null, ""), track("de", "asr", "&variant=timing-optimized"));

        List<Pick> picks = UtubotClientCaptions.select(all, "en-US");

        assertEquals(2, picks.size());
        assertEquals("de", picks.get(0).lang);
        assertEquals("auto", picks.get(0).kind);
        assertTrue(picks.get(0).original);
        assertTrue(picks.get(0).url, picks.get(0).url.contains("fmt=json3"));
        assertEquals("en", picks.get(1).lang);
        assertEquals("manual", picks.get(1).kind);
        assertFalse(picks.get(1).original);
    }

    @Test
    public void oneTrackWhenTheOriginalIsTheUsersLanguage() {
        List<Pick> picks = UtubotClientCaptions.select(Arrays.asList(track("en", "asr", ""), track("de", null, "")), "en");

        assertEquals(1, picks.size());
        assertEquals("en", picks.get(0).lang);
        assertTrue(picks.get(0).original);
    }

    @Test
    public void translatedOnlyAndNoTracksPickNothing() {
        assertTrue(UtubotClientCaptions.select(Collections.singletonList(track("en", "asr", "&tlang=de")), "en").isEmpty());
        assertTrue(UtubotClientCaptions.select(null, "en").isEmpty());
        assertTrue(UtubotClientCaptions.select(Collections.emptyList(), "en").isEmpty());
    }

    @Test
    public void authoredTracksOnlyTakeTheFirstAsTheOriginalWhenNoneIsInTheUsersLanguage() {
        List<Pick> picks = UtubotClientCaptions.select(Arrays.asList(track("de", null, ""), track("fr", null, "")), "en");

        assertEquals(1, picks.size());
        assertEquals("de", picks.get(0).lang);
        assertEquals("manual", picks.get(0).kind);
    }

    @Test
    public void claimsAVideoOncePerSession() {
        assertTrue(UtubotClientCaptions.claim("aaaaaaaaaaa"));
        assertFalse(UtubotClientCaptions.claim("aaaaaaaaaaa"));
        UtubotClientCaptions.release("aaaaaaaaaaa");
        assertTrue(UtubotClientCaptions.claim("aaaaaaaaaaa"));
    }

    @Test
    public void handOverUploadsTheFetchedBodiesAndSkipsOversizedOnes() throws Exception {
        List<MediaSubtitle> all = Arrays.asList(track("de", "asr", ""), track("en", null, ""));
        List<Pick> picks = UtubotClientCaptions.select(all, "en");
        List<ClientCaptionTrack> sent = new ArrayList<>();

        UtubotClientCaptions.handOver("abc", picks, url -> url.contains("lang=de") ? null : "{\"events\":[]}", (id, tracks) -> sent.addAll(tracks));

        assertEquals(1, sent.size());
        assertEquals("en", sent.get(0).lang);
        assertEquals("json3", sent.get(0).format);
    }

    @Test
    public void handOverUploadsNothingWhenNoBodyCame() throws Exception {
        List<Pick> picks = UtubotClientCaptions.select(Collections.singletonList(track("en", "asr", "")), "en");
        AtomicReference<String> sent = new AtomicReference<>();

        UtubotClientCaptions.handOver("abc", picks, url -> "  ", (id, tracks) -> sent.set(id));

        assertEquals(null, sent.get());
    }

    @Test
    public void aFailedFetchPropagatesSoTheCallerCanLogItAndTryAgainNextPlay() {
        List<Pick> picks = UtubotClientCaptions.select(Collections.singletonList(track("en", "asr", "")), "en");

        try {
            UtubotClientCaptions.handOver("abc", picks, url -> {
                throw new IOException("HTTP 429");
            }, (id, tracks) -> { });
            org.junit.Assert.fail("expected the fetch error");
        } catch (IOException expected) {
            assertEquals("HTTP 429", expected.getMessage());
        }
    }

    @Test
    public void clientPostsTheTracksToTheCaptionsClientRouteWithTheToken() throws Exception {
        TinyHttpServer server = new TinyHttpServer();
        AtomicReference<String> seen = new AtomicReference<>();
        AtomicReference<String> auth = new AtomicReference<>();
        server.on("/v1/videos/abc/captions/client", request -> {
            seen.set(request.method + " " + request.body);
            auth.set(request.headers.get("authorization"));
            return new TinyHttpServer.Response(200, "{\"stored\":true,\"reason\":\"stored\"}");
        });

        try {
            boolean stored = new UtubotClient("http://127.0.0.1:" + server.getPort() + "/", TOKEN).uploadCaptions("abc",
                    Collections.singletonList(new ClientCaptionTrack("en", "auto", "English", "json3", "{\"events\":[]}", true)));

            assertTrue(stored);
            assertEquals("Bearer " + TOKEN, auth.get());
            assertTrue(seen.get().startsWith("POST "));
            JSONObject track = new JSONObject(seen.get().substring("POST ".length())).getJSONArray("tracks").getJSONObject(0);
            assertEquals("en", track.getString("lang"));
            assertEquals("auto", track.getString("kind"));
            assertEquals("json3", track.getString("format"));
            assertEquals("{\"events\":[]}", track.getString("body"));
            assertTrue(track.getBoolean("original"));
        } finally {
            server.stop();
        }
    }
}
