package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotStremioClient.ImportedItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotStremioClient.ImportResult;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * The Stremio library client against a local fake backend (no real network): the connection status,
 * the mapped items and counts, and failure messages that never quote the backend address.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotStremioClientTest {
    private static final String BACKEND = "https://backend.example.com";
    private TinyHttpServer mServer;
    private final AtomicReference<String> mMethod = new AtomicReference<>();
    private final AtomicReference<String> mPath = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
    }

    @After
    public void stop() {
        mServer.stop();
    }

    private UtubotStremioClient client() {
        return new UtubotStremioClient("http://127.0.0.1:" + mServer.getPort(), "the-token");
    }

    @Test
    public void statusReflectsTheBackendFlag() throws Exception {
        mServer.on("/v1/films/stremio/status", request -> new TinyHttpServer.Response(200, "{\"set\":true}"));

        assertTrue(client().status());

        mServer.on("/v1/films/stremio/status", request -> new TinyHttpServer.Response(200, "{\"set\":false}"));
        assertFalse(client().status());
    }

    @Test
    public void statusUsesAGet() throws Exception {
        mServer.on("/v1/films/stremio/status", request -> {
            mMethod.set(request.method);
            mPath.set(request.path);
            return new TinyHttpServer.Response(200, "{\"set\":true}");
        });

        client().status();

        assertEquals("GET", mMethod.get());
        assertEquals("/v1/films/stremio/status", mPath.get());
    }

    @Test
    public void importReturnsTheItemsAndTheCounts() throws Exception {
        String body = "{\"watchlist\":2,\"resume\":1,\"watched\":1,\"unmapped\":0,\"items\":["
                + "{\"id\":\"tt0944947\",\"type\":\"series\",\"title_id\":\"tt0944947\",\"name\":\"Show\",\"poster\":\"http://p/s.jpg\",\"season\":0,\"episode\":0,\"position_ms\":120000,\"watched\":false,\"last_watched\":1000},"
                + "{\"id\":\"tt0944947:1:1\",\"type\":\"series\",\"title_id\":\"tt0944947\",\"name\":\"Show\",\"poster\":\"http://p/s.jpg\",\"season\":1,\"episode\":1,\"position_ms\":0,\"watched\":true,\"last_watched\":1001},"
                + "{\"id\":\"tt0111161\",\"type\":\"movie\",\"title_id\":\"tt0111161\",\"name\":\"Film\",\"poster\":\"http://p/m.jpg\",\"season\":0,\"episode\":0,\"position_ms\":0,\"watched\":false,\"last_watched\":0}]}";

        mServer.on("/v1/films/stremio/import", request -> {
            mMethod.set(request.method);
            return new TinyHttpServer.Response(200, body);
        });

        ImportResult result = client().importLibrary();

        assertEquals("POST", mMethod.get());
        assertEquals(3, result.items.size());
        assertEquals(2, result.watchlistCount);
        assertEquals(1, result.resumeCount);
        assertEquals(1, result.watchedCount);
        assertEquals(0, result.unmappedCount);

        ImportedItem series = result.items.get(0);

        assertEquals("tt0944947", series.id);
        assertEquals("series", series.type);
        assertEquals("tt0944947", series.titleId);
        assertEquals(120000L, series.positionMs);
        assertFalse(series.watched);
        assertTrue(series.isTitleLevel());
    }

    @Test
    public void aNonSuccessfulAnswerFailsWithoutTheAddress() throws Exception {
        mServer.on("/v1/films/stremio/status", request -> new TinyHttpServer.Response(500, "boom"));

        try {
            client().status();
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("HTTP 500"));
            assertFalse(expected.getMessage().contains(BACKEND));
        }
    }

    @Test
    public void anAnswerThatIsNotJsonFails() throws Exception {
        mServer.on("/v1/films/stremio/status", request -> new TinyHttpServer.Response(200, "<html>nope</html>"));

        try {
            client().status();
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("not readable"));
        }
    }

    @Test
    public void anUnreachableBackendFailsWithoutTheAddress() throws Exception {
        int port = mServer.getPort();
        mServer.stop();

        try {
            client().status();
            fail("expected an IOException");
        } catch (IOException expected) {
            assertFalse(expected.getMessage().contains("127.0.0.1"));
        }
    }

    @Test
    public void aBlankAnswerMeansNotConnected() throws Exception {
        mServer.on("/v1/films/stremio/status", request -> new TinyHttpServer.Response(200, "{}"));

        assertFalse(client().status());
    }

    @Test
    public void theImportOfAnEmptyLibraryHasNoItems() throws Exception {
        mServer.on("/v1/films/stremio/import", request -> new TinyHttpServer.Response(200, "{\"watchlist\":0,\"resume\":0,\"watched\":0,\"unmapped\":0,\"items\":[]}"));

        ImportResult result = client().importLibrary();

        assertEquals(0, result.items.size());
        assertTrue(result.items.isEmpty());
    }
}
