package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotProcessedClientTest {
    private static final String TOKEN = "secret-token";
    private static final String ITEM = "{\"video_id\":\"dQw4w9WgXcQ\",\"title\":\"A video\"," +
            "\"thumbnail\":\"https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg\",\"updated_at\":1763900000.0,\"summary\":true," +
            "\"captions\":[{\"job_id\":\"job1\",\"lang\":\"en\",\"translate_to\":\"de\",\"state\":\"ready\",\"progress\":1.0," +
            "\"error\":null,\"created_at\":1763899900.0,\"updated_at\":1763900000.0}]," +
            "\"cuts\":[{\"request_id\":\"cut1\",\"state\":\"ready\",\"preset_id\":\"cut-demo\",\"preset_label\":\"Only the demo\"," +
            "\"prompt\":null,\"error\":null,\"created_at\":1763899700.0,\"updated_at\":1763899800.0}]}";
    private TinyHttpServer mServer;
    private final AtomicReference<String> mQuery = new AtomicReference<>();
    private final AtomicReference<String> mAuth = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/processed", request -> {
            mAuth.set(request.headers.get("authorization"));
            mQuery.set(request.query);
            return new TinyHttpServer.Response(200, "{\"videos\":[" + ITEM + "]}");
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
    public void processedReadsTheVideosWithTheirLimitAndToken() throws IOException {
        ProcessedList list = new UtubotClient(base(), TOKEN).processed(50);

        assertEquals(1, list.videos.size());
        assertEquals("dQw4w9WgXcQ", list.videos.get(0).videoId);
        assertEquals("A video", list.videos.get(0).title);
        assertTrue(list.videos.get(0).summary);
        assertEquals("job1", list.videos.get(0).captions.get(0).jobId);
        assertEquals("Only the demo", list.videos.get(0).cuts.get(0).presetLabel);
        assertEquals("limit=50", mQuery.get());
        assertEquals("Bearer " + TOKEN, mAuth.get());
    }

    @Test
    public void aZeroLimitUsesTheBackendsDefault() throws IOException {
        new UtubotClient(base(), TOKEN).processed(0);

        assertEquals("", mQuery.get());
    }

    @Test
    public void theLimitValidationIsTheBackends() throws IOException {
        mServer.on("/v1/processed", request -> new TinyHttpServer.Response(400, "{\"error\":\"limit out of range\"}"));

        try {
            new UtubotClient(base(), TOKEN).processed(500);
            fail();
        } catch (UtubotClient.HttpException error) {
            assertEquals(400, error.code);
        }
    }
}
