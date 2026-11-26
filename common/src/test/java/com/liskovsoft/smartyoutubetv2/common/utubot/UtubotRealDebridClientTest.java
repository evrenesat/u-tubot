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
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * The Real-Debrid spike's Stremio addon client: it parses a Stremio addon's streams answer (Torrentio's lowercase fields, the capitalized
 * ones, a bare array), builds the address the player reads (the Real-Debrid token added to a Real-Debrid link, never to a direct one), and
 * reads them from the addon over HTTP.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotRealDebridClientTest {
    private TinyHttpServer mServer;
    private final AtomicReference<String> mPath = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/Streams/", request -> {
            mPath.set(request.path);
            return new TinyHttpServer.Response(200, request.body);
        });
    }

    @After
    public void stop() {
        mServer.stop();
    }

    @Test
    public void parsesTorrentioStyleStreams() throws Exception {
        String body = "{\"Streams\":["
                + "{\"name\":\"Film [2160p] [Real-Debrid] HEVC BluRay\",\"url\":\"https://realdebrid/direct/file.mp4\",\"info\":{\"resolution\":\"2160p\",\"bytes\":2147483648},"
                + "\"behaviorHints\":{\"resolutions\":[\"2160\"]}},"
                + "{\"name\":\"Film [1080p] torrent\",\"infoHash\":\"abcdef0123456789\",\"title\":\"Film (2020) [1080p]\"}"
                + "]}";

        List<Stream> streams = UtubotRealDebridClient.parseStreams(body);

        assertEquals(2, streams.size());
        Stream first = streams.get(0);
        assertEquals("Film [2160p] [Real-Debrid] HEVC BluRay", first.name);
        assertEquals("https://realdebrid/direct/file.mp4", first.url);
        assertEquals(2160, first.resolution);
        assertEquals(2147483648L, first.sizeBytes);
        assertTrue(first.isRealDebrid);
        assertTrue(first.isDirectPlayable());

        Stream second = streams.get(1);
        assertNull(second.url);
        assertEquals("abcdef0123456789", second.infoHash);
        assertEquals(1080, second.resolution);
        assertFalse(second.isDirectPlayable());
    }

    @Test
    public void parsesCapitalizedFieldsAndBareArray() throws Exception {
        // A bare array of entries with the capitalized Stremio field names.
        String body = "[{\"Name\":\"Movie [720p]\",\"Url\":\"http://host/movie.mkv\"}]";
        List<Stream> streams = UtubotRealDebridClient.parseStreams(body);

        assertEquals(1, streams.size());
        assertEquals("http://host/movie.mkv", streams.get(0).url);
        assertEquals(720, streams.get(0).resolution);

        // The capitalized Name/Url form, wrapped.
        String wrapped = "{\"Streams\":[{\"Name\":\"Movie 2\",\"Url\":\"http://host/2.mkv\",\"InfoHash\":\"deadbeef\"}]}";
        List<Stream> wrappedStreams = UtubotRealDebridClient.parseStreams(wrapped);

        assertEquals(1, wrappedStreams.size());
        assertEquals("deadbeef", wrappedStreams.get(0).infoHash);
    }

    @Test
    public void aBdLinkIsRealDebridEvenWithoutANameHint() throws Exception {
        List<Stream> streams = UtubotRealDebridClient.parseStreams(
                "{\"Streams\":[{\"name\":\"RD torrent\",\"url\":\"bd:c244b7c8b7f5a1e2d3c4\"}]}");

        assertEquals(1, streams.size());
        assertTrue(streams.get(0).isRealDebrid);
        assertTrue(streams.get(0).isDirectPlayable());
    }

    @Test
    public void aStreamWithNeitherUrlNorHashIsDropped() throws Exception {
        List<Stream> streams = UtubotRealDebridClient.parseStreams(
                "{\"Streams\":[{\"name\":\"empty entry\",\"title\":\"nothing here\"}]}");

        assertTrue(streams.isEmpty());
    }

    @Test
    public void aBlankAnswerHasNoStreams() throws Exception {
        assertTrue(UtubotRealDebridClient.parseStreams("").isEmpty());
        assertTrue(UtubotRealDebridClient.parseStreams("   ").isEmpty());
    }

    @Test
    public void theTokenIsAddedToARealDebridLinkNotToAPlainOne() throws Exception {
        UtubotRealDebridClient client = new UtubotRealDebridClient("https://addon.example", "rdtoken123");

        Stream rd = new Stream("RD", "bd:abc123", null, 2160, 0);
        assertEquals("bd:abc123?token=rdtoken123", client.playbackUrl(rd));

        Stream plain = new Stream("Plain", "http://cdn/file.mkv", null, 1080, 0);
        assertEquals("http://cdn/file.mkv", client.playbackUrl(plain));
    }

    @Test
    public void theTokenRidesOnAnExistingQueryWithoutADuplicateQuestionMark() throws Exception {
        assertEquals("http://cdn/file?x=1&token=tok",
                UtubotRealDebridClient.applyToken("http://cdn/file?x=1", "tok"));
        assertEquals("http://cdn/file?token=tok",
                UtubotRealDebridClient.applyToken("http://cdn/file", "tok"));
    }

    @Test
    public void withoutATokenARealDebridLinkPlaysAsItsRawAddress() throws Exception {
        UtubotRealDebridClient client = new UtubotRealDebridClient("https://addon.example", "");
        Stream rd = new Stream("RD", "bd:abc123", null, 2160, 0);
        assertEquals("bd:abc123", client.playbackUrl(rd));
    }

    @Test
    public void readsTheStreamsFromTheAddonOverHttp() throws Exception {
        mServer.on("/Streams/", request -> {
            mPath.set(request.path);
            return new TinyHttpServer.Response(200,
                    "{\"Streams\":[{\"name\":\"Film [1080p]\",\"url\":\"http://cdn/film.mkv\"}]}");
        });

        UtubotRealDebridClient client = new UtubotRealDebridClient("http://127.0.0.1:" + mServer.getPort() + "/", "");
        List<Stream> streams = client.streams("tt0944947");

        assertEquals(1, streams.size());
        assertEquals("http://cdn/film.mkv", streams.get(0).url);
        assertEquals("/Streams/tt0944947", mPath.get());
    }

    @Test
    public void aNonSuccessfulAddonAnswerFails() throws Exception {
        mServer.on("/Streams/", request -> new TinyHttpServer.Response(500, "boom"));

        UtubotRealDebridClient client = new UtubotRealDebridClient("http://127.0.0.1:" + mServer.getPort() + "/", "");

        try {
            client.streams("tt0000000");
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("HTTP 500"));
        }
    }

    @Test
    public void aMissingAddonOrIdFailsWithoutANetworkCall() throws Exception {
        UtubotRealDebridClient client = new UtubotRealDebridClient("", "token");

        try {
            client.streams("tt0000000");
            fail("expected an IOException");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("addon address"));
        }
    }

    @Test
    public void resolutionIsReadFromBehaviorHintsOrTheName() throws Exception {
        List<Stream> hint = UtubotRealDebridClient.parseStreams(
                "{\"Streams\":[{\"name\":\"No hint marker\",\"url\":\"http://cdn/h.mkv\",\"behaviorHints\":{\"resolutions\":[\"480\",\"1080\"]}}]}");
        assertEquals(1080, hint.get(0).resolution);

        List<Stream> fromName = UtubotRealDebridClient.parseStreams(
                "{\"Streams\":[{\"name\":\"Movie 4K x265\",\"url\":\"http://cdn/4k.mkv\"}]}");
        assertEquals(2160, fromName.get(0).resolution);
    }
}
