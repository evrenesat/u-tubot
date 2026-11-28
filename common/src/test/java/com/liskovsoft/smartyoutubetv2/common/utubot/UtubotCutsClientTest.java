package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutsClientTest {
    private static final String TOKEN = "secret-token";
    private static final String CUT = "{\"version\":1,\"video_id\":\"abcdefghijk\",\"transcript_hash\":\"t1\",\"duration_ms\":240000," +
            "\"label\":\"No filler\",\"summary\":\"s\",\"parts\":[{\"label\":\"Start\",\"start_ms\":0,\"end_ms\":60000}]," +
            "\"skip_ranges_ms\":[[60000,108000]],\"kept_ms\":192000,\"source\":\"youtube_captions\",\"preset_id\":\"cut-no-filler\"," +
            "\"model\":\"fast\",\"built_at\":\"2026-11-20T10:00:00Z\"}";
    private TinyHttpServer mServer;
    private final AtomicReference<String> mQuery = new AtomicReference<>();
    private final AtomicReference<String> mBody = new AtomicReference<>();
    private final AtomicReference<String> mAuth = new AtomicReference<>();
    private final AtomicReference<String> mMethod = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/videos/abcdefghijk/cuts", request -> {
            mAuth.set(request.headers.get("authorization"));
            mQuery.set(request.query);

            if ("POST".equals(request.method)) {
                mBody.set(request.body);
                return new TinyHttpServer.Response(200, "{\"request_id\":\"cut1\",\"state\":\"waiting\"}");
            }

            return new TinyHttpServer.Response(200, "{\"configured\":true,\"presets\":[" +
                    "{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\",\"request_id\":\"cut1\",\"cut\":" + CUT + "}," +
                    "{\"id\":\"cut-answer\",\"label\":\"Just the answer\",\"state\":\"none\"}]}");
        });
        mServer.on("/v1/videos/f7bb94acc21/cuts", request -> {
            mAuth.set(request.headers.get("authorization"));
            mQuery.set(request.query);

            if ("POST".equals(request.method)) {
                mBody.set(request.body);
                return new TinyHttpServer.Response(200, "{\"request_id\":\"cut9\",\"state\":\"building\"}");
            }

            return new TinyHttpServer.Response(200, "{\"configured\":true,\"presets\":[]}");
        });
        mServer.on("/v1/videos/abcdefghijk/cut-choice", request -> {
            mAuth.set(request.headers.get("authorization"));
            mBody.set(request.body);
            return new TinyHttpServer.Response(200, "{\"ok\":true}");
        });
        mServer.on("/v1/cut-channels/UCabc", request -> {
            mAuth.set(request.headers.get("authorization"));
            mQuery.set(request.query);
            mBody.set(request.body);
            mMethod.set(request.method);
            return new TinyHttpServer.Response(200, "{\"channel_id\":\"UCabc\",\"mode\":\"quick\"}");
        });
        mServer.on("/v1/cuts/cut1", request -> {
            mAuth.set(request.headers.get("authorization"));
            mQuery.set(request.query);
            return new TinyHttpServer.Response(200, "{\"id\":\"cut1\",\"video_id\":\"abcdefghijk\",\"state\":\"ready\"," +
                    "\"source\":\"TV\",\"preset_id\":\"cut-no-filler\",\"title\":\"A video\",\"duration_s\":240,\"cut\":" + CUT + "}");
        });
        mServer.on("/v1/cut-requests/cut1", request -> {
            mAuth.set(request.headers.get("authorization"));
            mBody.set(request.body);
            mMethod.set(request.method);
            return new TinyHttpServer.Response(200, "{\"id\":\"cut1\",\"video_id\":\"abcdefghijk\",\"state\":\"building\",\"mode\":\"quick\"}");
        });
    }

    @After
    public void stop() {
        mServer.stop();
    }

    private String base() {
        return "http://127.0.0.1:" + mServer.getPort() + "/";
    }

    @Test
    public void cutsReadsThePresets() throws IOException {
        UtubotClient client = new UtubotClient(base(), TOKEN);
        CutList cuts = client.cuts("abcdefghijk");

        assertTrue(cuts.configured);
        assertEquals(2, cuts.presets.size());
        assertTrue(cuts.presets.get(0).isReady());
        assertEquals(60_000, cuts.presets.get(0).cut.skipRangesMs.get(0)[0]);
        assertEquals("Bearer " + TOKEN, mAuth.get());
    }

    @Test
    public void cutsSendsTheChannelId() throws IOException {
        UtubotClient client = new UtubotClient(base(), TOKEN);
        VideoMeta meta = new VideoMeta();
        meta.videoId = "abcdefghijk";
        meta.channel = "A channel";
        meta.channelId = "UCabc";

        CutList cuts = client.cuts("abcdefghijk", meta);

        assertTrue(cuts.configured);
        assertTrue(URLDecoder.decode(mQuery.get(), StandardCharsets.UTF_8).contains("channel_id=UCabc"));
    }

    @Test
    public void channelModeIsSetAndCleared() throws IOException {
        UtubotClient client = new UtubotClient(base(), TOKEN);

        client.setChannelMode("UCabc", "quick", "A channel");
        assertEquals("PUT", mMethod.get());
        assertEquals("{\"mode\":\"quick\",\"channel_name\":\"A channel\"}", mBody.get());

        client.clearChannelMode("UCabc");
        assertEquals("DELETE", mMethod.get());
    }

    @Test
    public void requestCutWithAPreset_sendsTheBodyAndTheVideoFacts() throws IOException {
        UtubotClient client = new UtubotClient(base(), TOKEN);
        VideoMeta meta = new VideoMeta();
        meta.videoId = "abcdefghijk";
        meta.title = "A video & more";
        meta.channel = "A channel";
        meta.durationSec = 240;

        CutRequest request = client.requestCut("abcdefghijk", "cut-no-filler", null, false, meta);

        assertEquals("cut1", request.id);
        assertEquals("waiting", request.state);
        assertEquals("{\"preset\":\"cut-no-filler\"}", mBody.get());
        String query = URLDecoder.decode(mQuery.get(), StandardCharsets.UTF_8);
        assertTrue(query.contains("title=A video & more"));
        assertTrue(query.contains("channel=A channel"));
        assertTrue(query.contains("duration_s=240"));
    }

    @Test
    public void requestCutWithAWatchedMode_sendsTheMode() throws IOException {
        new UtubotClient(base(), TOKEN).requestCut("abcdefghijk", "cut-demo", null, false, null, "watched");

        assertEquals("{\"preset\":\"cut-demo\",\"mode\":\"watched\"}", mBody.get());
    }

    @Test
    public void requestCutWithForce_sendsForce() throws IOException {
        new UtubotClient(base(), TOKEN).requestCut("abcdefghijk", "cut-no-filler", null, false, null, true);

        assertEquals("{\"force\":true,\"preset\":\"cut-no-filler\"}", mBody.get());
    }

    @Test
    public void requestCutAwaitingThePrompt_sendsAwaitPrompt() throws IOException {
        new UtubotClient(base(), TOKEN).requestCut("abcdefghijk", null, null, true, null);

        assertEquals("{\"await_prompt\":true}", mBody.get());
    }

    @Test
    public void requestCutWithAPrompt_sendsThePrompt() throws IOException {
        new UtubotClient(base(), TOKEN).requestCut("abcdefghijk", null, "Keep the demo", false, null);

        assertEquals("{\"prompt\":\"Keep the demo\"}", mBody.get());
    }

    @Test
    public void chooseCut_sendsThePresetChoice() throws IOException {
        new UtubotClient(base(), TOKEN).chooseCut("abcdefghijk", "cut-demo", null, false);

        assertEquals("{\"preset\":\"cut-demo\"}", mBody.get());
        assertEquals("Bearer " + TOKEN, mAuth.get());
    }

    @Test
    public void chooseCutCanTurnTheCutOff() throws IOException {
        new UtubotClient(base(), TOKEN).chooseCut("abcdefghijk", null, null, true);

        assertEquals("{\"off\":true}", mBody.get());
    }

    @Test
    public void cutLongPolls() throws IOException {
        CutRequest request = new UtubotClient(base(), TOKEN).cut("cut1", 10_000);

        assertTrue(request.isReady());
        assertTrue(mQuery.get().contains("wait_ms=10000"));
        assertEquals("No filler", request.cut.label);
    }

    @Test
    public void theCutRequestUrlIsTheShortAddress() throws IOException {
        UtubotClient client = new UtubotClient(base(), TOKEN);

        assertEquals(base() + "cuts/cut1", client.cutRequestUrl("cut1"));
    }

    @Test
    public void fillCutRequest_sendsThePromptAndMode() throws IOException {
        CutRequest request = new UtubotClient(base(), TOKEN).fillCutRequest("cut1", "Keep the demo", "watched");

        assertEquals("PUT", mMethod.get());
        assertEquals("{\"prompt\":\"Keep the demo\",\"mode\":\"watched\"}", mBody.get());
        assertEquals("Bearer " + TOKEN, mAuth.get());
        assertEquals("building", request.state);
    }

    @Test
    public void fillCutRequestWithoutMode_omitsTheMode() throws IOException {
        new UtubotClient(base(), TOKEN).fillCutRequest("cut1", "Keep the demo", null);

        assertEquals("{\"prompt\":\"Keep the demo\"}", mBody.get());
    }

    private static UtubotFilmPlay film() {
        UtubotFilmPlay film = new UtubotFilmPlay("tt0111161", "movie", "tt0111161", "The Movie", "https://img.example/p.jpg", 0, 0,
                "https://host/secret-key/file.mkv", "Movie.mkv", 0, 1234);
        film.setReleaseDurationMs(7_200_000);
        film.setStreamFps(23.976f);
        film.setSubtitleLanguage("tr");
        return film;
    }

    @Test
    public void aFilmCutRequestNamesItsReleaseAndNothingAboutTheViewer() throws IOException {
        UtubotFilmPlay film = film();
        VideoMeta meta = UtubotMeta.from(com.liskovsoft.smartyoutubetv2.common.app.models.data.Video.fromFilm(film));
        UtubotClient client = new UtubotClient(base(), TOKEN);

        CutRequest request = client.requestCut(film.videoId(), "cut-skim-film", null, false, meta);

        assertEquals("f7bb94acc21", film.videoId());
        assertEquals("cut9", request.id);
        assertEquals("{\"preset\":\"cut-skim-film\"}", mBody.get());
        String query = URLDecoder.decode(mQuery.get(), StandardCharsets.UTF_8);
        assertTrue(query, query.contains("source_kind=film"));
        assertTrue(query, query.contains("source_key=imdb:tt0111161"));
        assertTrue(query, query.contains("release_key=Movie.mkv|1234"));
        assertTrue(query, query.contains("release_duration_ms=7200000"));
        assertTrue(query, query.contains("duration_s=7200"));
        assertTrue(query, query.contains("title=The Movie"));
        assertTrue(query, query.contains("sub_lang=tr"));
        assertTrue(query, query.contains("stream_fps=23.976"));
        assertTrue(query, query.contains("poster=https://img.example/p.jpg"));
        assertFalse(query, query.contains("secret-key")); // the stream address can carry a key
        assertFalse(query, query.contains("channel"));
    }

    @Test
    public void theCutListOfAFilmCarriesTheReleaseToo() throws IOException {
        UtubotFilmPlay film = film();
        VideoMeta meta = UtubotMeta.from(com.liskovsoft.smartyoutubetv2.common.app.models.data.Video.fromFilm(film));

        new UtubotClient(base(), TOKEN).cuts(film.videoId(), meta);

        assertTrue(URLDecoder.decode(mQuery.get(), StandardCharsets.UTF_8).contains("source_key=imdb:tt0111161"));
    }

    @Test
    public void aYouTubeVideoSendsNoFilmFacts() throws IOException {
        VideoMeta meta = new VideoMeta();
        meta.videoId = "abcdefghijk";
        meta.title = "A video";

        new UtubotClient(base(), TOKEN).cuts("abcdefghijk", meta);

        assertFalse(mQuery.get().contains("source_kind"));
    }
}
