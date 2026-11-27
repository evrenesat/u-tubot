package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient.Stream;

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
 * The Real-Debrid spike's Stremio addon client against a local fake addon (no real network): the stream list, direct addresses only, the
 * token placeholder, and failure messages that never quote the addon address.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotRealDebridClientTest {
    private static final String SECRET = "SECRETKEY123";
    private TinyHttpServer mServer;
    private final AtomicReference<String> mPath = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
    }

    @After
    public void stop() {
        mServer.stop();
    }

    private String base() {
        return "http://127.0.0.1:" + mServer.getPort();
    }

    @Test
    public void parsesDirectStreamsAndDropsTorrentOnlyEntries() throws Exception {
        String body = "{\"streams\":["
                + "{\"name\":\"Torrentio\\n4k HDR\",\"title\":\"Film 2160p HEVC\",\"url\":\"https://cdn.example/f.mkv\","
                + "\"behaviorHints\":{\"videoSize\":2147483648}},"
                + "{\"name\":\"torrent\",\"infoHash\":\"abcdef0123456789\"}]}";

        List<Stream> streams = UtubotRealDebridClient.parseStreams(body);

        assertEquals(1, streams.size());
        assertEquals("https://cdn.example/f.mkv", streams.get(0).url);
        assertEquals(2160, streams.get(0).resolution);
        assertEquals(2147483648L, streams.get(0).sizeBytes);
        assertTrue(streams.get(0).display().contains("2.0 GB"));
        assertFalse(streams.get(0).display().contains("cdn.example"));
    }

    @Test
    public void aBareArrayAndABlankAnswerAreAccepted() throws Exception {
        assertEquals(1, UtubotRealDebridClient.parseStreams("[{\"name\":\"Movie 720p\",\"url\":\"http://h/m.mkv\"}]").size());
        assertTrue(UtubotRealDebridClient.parseStreams("  ").isEmpty());
    }

    @Test
    public void nonHttpAddressesAreDropped() throws Exception {
        assertTrue(UtubotRealDebridClient.parseStreams("{\"streams\":[{\"name\":\"x\",\"url\":\"magnet:?xt=1\"}]}").isEmpty());
    }

    @Test
    public void readsTheStreamsFromTheAddonWithAGet() throws Exception {
        mServer.on("/stream/movie/", request -> {
            mPath.set(request.method + " " + request.path);
            return new TinyHttpServer.Response(200, "{\"streams\":[{\"name\":\"Film 1080p\",\"url\":\"http://cdn/film.mkv\"}]}");
        });

        List<Stream> streams = new UtubotRealDebridClient(base() + "/", "").streams(" tt0944947 ");

        assertEquals(1, streams.size());
        assertEquals("GET /stream/movie/tt0944947.json", mPath.get());
    }

    @Test
    public void theTokenReplacesThePlaceholderInTheAddonAddress() throws Exception {
        mServer.on("/", request -> {
            mPath.set(request.path);
            return new TinyHttpServer.Response(200, "{\"streams\":[]}");
        });

        new UtubotRealDebridClient(base() + "/realdebrid=" + UtubotRealDebridClient.TOKEN_PLACEHOLDER, " " + SECRET + " ").streams("tt1");

        assertEquals("/realdebrid=" + SECRET + "/stream/movie/tt1.json", mPath.get());
    }

    @Test
    public void aNonSuccessfulAnswerFailsWithoutTheAddress() throws Exception {
        mServer.on("/", request -> new TinyHttpServer.Response(500, "boom"));

        try {
            new UtubotRealDebridClient(base() + "/" + SECRET, "").streams("tt0000000");
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("HTTP 500"));
            assertFalse(expected.getMessage().contains(SECRET));
        }
    }

    @Test
    public void anUnreachableAddonFailsWithoutTheAddress() throws Exception {
        int port = mServer.getPort();
        mServer.stop();

        try {
            new UtubotRealDebridClient("http://127.0.0.1:" + port + "/" + SECRET, "").streams("tt0000000");
            fail("expected an IOException");
        } catch (IOException expected) {
            assertFalse(expected.getMessage().contains(SECRET));
            assertFalse(expected.getMessage().contains("127.0.0.1"));
        }
    }

    @Test
    public void anAnswerThatIsNotAStreamListFails() throws Exception {
        mServer.on("/", request -> new TinyHttpServer.Response(200, "<html>nope</html>"));

        try {
            new UtubotRealDebridClient(base(), "").streams("tt1");
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("not a stream list"));
        }
    }

    @Test
    public void aMissingAddonOrIdFailsWithoutANetworkCall() throws Exception {
        try {
            new UtubotRealDebridClient("", "token").streams("tt0000000");
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("addon address"));
        }
    }
}
