package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotClient.CutCache;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The cut list with its ETag (`GET /v1/videos/{id}/cuts`): a fresh list with what to cache, or a 304 when
 * the stored ETag matched and the client keeps its copy.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutsCacheClientTest {
    private static final String TOKEN = "secret-token";
    private static final String VIDEO = "abcdefghijk";
    private static final String ETAG = "\"list-1\"";
    private static final String CUT = "{\"version\":1,\"video_id\":\"abcdefghijk\",\"transcript_hash\":\"t1\",\"duration_ms\":240000,"
            + "\"label\":\"No filler\",\"summary\":\"s\",\"parts\":[{\"label\":\"Start\",\"start_ms\":0,\"end_ms\":60000}],"
            + "\"skip_ranges_ms\":[[60000,108000]],\"kept_ms\":192000,\"source\":\"youtube_captions\",\"preset_id\":\"cut-no-filler\",\"mode\":\"quick\"}";
    private static final String BODY = "{\"configured\":true,\"default_mode\":\"quick\",\"presets\":" +
            "[{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\",\"cut\":" + CUT + "}]}";
    private TinyHttpServer mServer;
    private final AtomicReference<String> mIfNoneMatch = new AtomicReference<>();
    private final AtomicReference<String> mAuth = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/videos/" + VIDEO + "/cuts", request -> {
            mAuth.set(request.headers.get("authorization"));
            mIfNoneMatch.set(request.headers.get("if-none-match"));

            if (ETAG.equals(request.headers.get("if-none-match"))) {
                TinyHttpServer.Response notModified = new TinyHttpServer.Response(304, "");
                notModified.headers.put("etag", ETAG);
                return notModified;
            }

            TinyHttpServer.Response response = new TinyHttpServer.Response(200, BODY);
            response.headers.put("etag", ETAG);
            return response;
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
    public void theFreshListCarriesItsBodyAndEtag() throws IOException {
        CutCache cache = new UtubotClient(base(), TOKEN).cutsCache(VIDEO, null, null);

        assertFalse(cache.notModified);
        assertNotNull(cache.cuts);
        assertTrue(cache.cuts.configured);
        assertEquals(ETAG, cache.etag);
        assertEquals(BODY, cache.body);
        assertEquals("Bearer " + TOKEN, mAuth.get());
    }

    @Test
    public void aMatchingIfNoneMatchAnswers304AndKeepsTheCache() throws IOException {
        CutCache cache = new UtubotClient(base(), TOKEN).cutsCache(VIDEO, ETAG, null);

        assertTrue(cache.notModified);
        assertNull(cache.cuts);
        assertNull(cache.body);
        assertEquals(ETAG, cache.etag);
        assertEquals(ETAG, mIfNoneMatch.get());
    }

    @Test
    public void aStaleIfNoneMatchIsIgnoredAndTheFreshListReturns() throws IOException {
        CutCache cache = new UtubotClient(base(), TOKEN).cutsCache(VIDEO, "\"old\"", null);

        assertFalse(cache.notModified);
        assertNotNull(cache.cuts);
        assertEquals(ETAG, cache.etag);
    }

    @Test
    public void anErrorStatusBecomesAnException() throws IOException {
        mServer.on("/v1/videos/abcdefghijkxy/cuts", request -> new TinyHttpServer.Response(500, "{}"));

        try {
            new UtubotClient(base(), TOKEN).cutsCache(VIDEO + "xy", null, null);
            throw new AssertionError("expected an error");
        } catch (IOException expected) {
            assertTrue(expected instanceof UtubotClient.HttpException);
            assertEquals(500, ((UtubotClient.HttpException) expected).code);
        }
    }
}
