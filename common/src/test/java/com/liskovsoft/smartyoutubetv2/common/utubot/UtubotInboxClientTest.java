package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxList;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * The Inbox client (u-tubot #160): the results list with its limit and token, and the read, read-all and dismiss writes carry the ids
 * to the backend.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotInboxClientTest {
    private static final String TOKEN = "secret-token";
    private static final String ITEM = "{\"id\":1,\"video_id\":\"dQw4w9WgXcQ\",\"kind\":\"cut\"," +
            "\"result_id\":\"cut1\",\"title\":\"A video\",\"length_s\":240,\"label\":\"Only the demo\"," +
            "\"thumbnail\":\"https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg\",\"created_at\":1763900000.0,\"read\":false}";
    private TinyHttpServer mServer;
    private final AtomicReference<String> mQuery = new AtomicReference<>();
    private final AtomicReference<String> mAuth = new AtomicReference<>();
    private final AtomicReference<String> mBody = new AtomicReference<>();
    private final AtomicReference<String> mMethod = new AtomicReference<>();

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/inbox", request -> {
            mAuth.set(request.headers.get("authorization"));
            mQuery.set(request.query);
            mMethod.set(request.method);

            if (request.path.endsWith("/read-all")) {
                mBody.set("{}");
            } else if (!request.path.equals("/v1/inbox")) {
                mBody.set(request.body);
            }

            return new TinyHttpServer.Response(200, "{\"unread\":1,\"items\":[" + ITEM + "]}");
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
    public void inboxReadsTheResultsWithTheirToken() throws IOException {
        InboxList list = new UtubotClient(base(), TOKEN).inbox(50);

        assertEquals(1, list.items.size());
        InboxItem item = list.items.get(0);
        assertEquals(1, item.id);
        assertEquals("dQw4w9WgXcQ", item.videoId);
        assertEquals(UtubotModels.InboxKind.CUT, item.kind);
        assertEquals("cut1", item.resultId);
        assertEquals("A video", item.title);
        assertEquals(240, item.lengthS);
        assertEquals("Only the demo", item.label);
        assertEquals("https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", item.thumbnail);
        assertEquals(1763900000.0, item.createdAt, 0.0);
        assertTrue(list.unread > 0);
        assertEquals("limit=50", mQuery.get());
        assertEquals("Bearer " + TOKEN, mAuth.get());
    }

    @Test
    public void aZeroLimitUsesTheBackendsDefault() throws IOException {
        new UtubotClient(base(), TOKEN).inbox(0);

        assertEquals("", mQuery.get());
    }

    @Test
    public void readInboxPostsTheIds() throws IOException {
        new UtubotClient(base(), TOKEN).readInbox(Collections.singletonList(7L));

        assertEquals("POST", mMethod.get());
        assertEquals("{\"ids\":[7]}", mBody.get());
    }

    @Test
    public void readAllInboxPostsNothing() throws IOException {
        new UtubotClient(base(), TOKEN).readAllInbox();

        assertEquals("POST", mMethod.get());
        assertEquals("{}", mBody.get());
    }

    @Test
    public void dismissInboxPostsTheIds() throws IOException {
        List<Long> ids = new ArrayList<>();
        ids.add(1L);
        ids.add(2L);
        new UtubotClient(base(), TOKEN).dismissInbox(ids);

        assertEquals("POST", mMethod.get());
        assertEquals("{\"ids\":[1,2]}", mBody.get());
    }

    @Test
    public void tooManyIdsIsRefusedWithoutCallingTheBackend() throws IOException {
        List<Long> ids = new ArrayList<>();

        for (int i = 0; i < 201; i++) {
            ids.add((long) i);
        }

        try {
            new UtubotClient(base(), TOKEN).dismissInbox(ids);
            fail();
        } catch (IOException error) {
            assertTrue(error.getMessage().contains("Too many inbox ids"));
        }
    }
}
