package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotClientTest {
    private static final String TOKEN = "secret-token";
    private static final int SLOW_MS = 3000;
    private TinyHttpServer mServer;
    private final AtomicReference<String> mAuth = new AtomicReference<>();
    private final AtomicReference<String> mBody = new AtomicReference<>();
    private final AtomicReference<String> mQuery = new AtomicReference<>();
    private volatile boolean mSlowAssess;
    private final String mAssessAnswer = "{\"results\":[{\"video_id\":\"a\",\"status\":\"ready\",\"action\":\"mark\",\"mark_label\":\"L\"}]}";

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/health", request -> new TinyHttpServer.Response(200, "{\"ok\":true,\"version\":\"0.1.0\"}"));
        mServer.on("/v1/me", request -> {
            mAuth.set(request.headers.get("authorization"));
            boolean ok = ("Bearer " + TOKEN).equals(mAuth.get());
            return new TinyHttpServer.Response(ok ? 200 : 401, ok ? "{\"user\":\"owner\",\"features\":{\"assess\":true}}" : "{\"error\":\"unauthorized\"}");
        });
        mServer.on("/v1/assess", request -> {
            mBody.set(request.body);

            if (mSlowAssess) {
                Thread.sleep(SLOW_MS);
            }

            return new TinyHttpServer.Response(200, mAssessAnswer);
        });
        mServer.on("/v1/pair", request -> {
            mBody.set(request.body);
            mAuth.set(request.headers.get("authorization"));
            return new TinyHttpServer.Response(200, "{\"token\":\"new-token\",\"user\":\"partner\"}");
        });
        mServer.on("/v1/videos/abc/summary", request -> {
            mQuery.set(request.query);
            return new TinyHttpServer.Response(200, "{\"video_id\":\"abc\",\"status\":\"ready\",\"text\":\"T\"}");
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
    public void healthNeedsNoToken() throws Exception {
        assertTrue(new UtubotClient(base(), "").health());
    }

    @Test
    public void meSendsTheBearerToken() throws Exception {
        assertEquals("owner", new UtubotClient(base(), TOKEN).me().user);
        assertEquals("Bearer " + TOKEN, mAuth.get());
    }

    @Test
    public void wrongTokenIsUnauthorized() throws Exception {
        try {
            new UtubotClient(base(), "bad").me();
            fail();
        } catch (UtubotClient.HttpException e) {
            assertTrue(e.isUnauthorized());
        }
    }

    @Test
    public void assessSendsTheContractBody() throws Exception {
        VideoMeta meta = new VideoMeta();
        meta.videoId = "a";
        meta.title = "Title";

        List<Verdict> verdicts = new UtubotClient(base(), TOKEN).assess(Collections.singletonList(meta), "home", 1200, 2000);

        JSONObject sent = new JSONObject(mBody.get());
        assertEquals("home", sent.getString("section"));
        assertEquals(1200, sent.getInt("wait_ms"));
        assertEquals("a", sent.getJSONArray("videos").getJSONObject(0).getString("video_id"));
        assertEquals("L", verdicts.get(0).markLabel);
    }

    @Test
    public void hardTimeoutCutsASlowCall() throws Exception {
        mSlowAssess = true;
        long start = System.currentTimeMillis();

        try {
            new UtubotClient(base(), TOKEN).assess(Collections.singletonList(new VideoMeta()), "home", 0, 300);
            fail();
        } catch (IOException expected) {
        }

        assertTrue(System.currentTimeMillis() - start < SLOW_MS);
    }

    @Test
    public void unreachableBackendThrows() {
        try {
            new UtubotClient("http://127.0.0.1:1", TOKEN).health();
            fail();
        } catch (IOException expected) {
            assertFalse(expected.getMessage() == null && expected.getCause() == null);
        }
    }

    @Test
    public void pairSendsCodeAndDeviceWithoutAuth() throws Exception {
        UtubotClient.PairResult result = new UtubotClient(base(), "").pair("123456", "Shield");

        assertEquals("new-token", result.token);
        assertEquals("partner", result.user);
        JSONObject sent = new JSONObject(mBody.get());
        assertEquals("123456", sent.getString("code"));
        assertEquals("Shield", sent.getString("device"));
        assertEquals(null, mAuth.get());
    }

    @Test
    public void summaryQueryCarriesPromptAndWait() throws Exception {
        new UtubotClient(base(), TOKEN).summary("abc", "set/prompt", null, 20000);

        assertTrue(mQuery.get().contains("prompt=set%2Fprompt") || mQuery.get().contains("prompt=set/prompt"));
        assertTrue(mQuery.get().contains("wait_ms=20000"));
    }

    @Test
    public void captionUrlIsAbsoluteAndTokenFreeAndTheHeaderStaysOnTheBackend() {
        UtubotClient client = new UtubotClient("https://host:8443/", TOKEN);

        assertEquals("https://host:8443/v1/videos/a/captions/en.vtt", client.captionUrl("/v1/videos/a/captions/en.vtt"));
        assertEquals("https://other/x.vtt", client.captionUrl("https://other/x.vtt"));
        assertEquals("Bearer " + TOKEN, client.authorizationFor("https://host:8443/v1/x.vtt"));
        assertNull(client.authorizationFor("https://other/x.vtt"));
        assertNull(new UtubotClient("https://host", "").authorizationFor("https://host/x.vtt"));
    }
}
