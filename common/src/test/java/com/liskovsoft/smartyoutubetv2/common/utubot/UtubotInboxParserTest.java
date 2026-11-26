package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxKind;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxList;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotInboxParserTest {
    private static final String CUT = "{\"id\":3,\"video_id\":\"dQw4w9WgXcQ\",\"kind\":\"cut\"," +
            "\"result_id\":\"cut1\",\"title\":\"A video\",\"length_s\":240,\"label\":\"Only the demo\"," +
            "\"thumbnail\":\"https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg\",\"created_at\":1763900000.0,\"read\":false}";
    private static final String SUMMARY = "{\"id\":2,\"video_id\":\"abcdefghijk\",\"kind\":\"summary\"," +
            "\"result_id\":\"kw-keep-the-demo\",\"prompt_key\":\"kw-keep-the-demo\",\"title\":null,\"length_s\":180," +
            "\"label\":null,\"thumbnail\":\"https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg\",\"created_at\":1763899000.0,\"read\":true}";
    private static final String RESEARCH = "{\"id\":1,\"video_id\":\"abcdefghijk\",\"kind\":\"research\"," +
            "\"result_id\":\"en\",\"title\":\"Research\",\"length_s\":null,\"label\":null,\"thumbnail\":null," +
            "\"created_at\":1763898000.0,\"read\":false}";
    private static final String CAPTIONS = "{\"id\":4,\"video_id\":\"abcdefghijk\",\"kind\":\"captions\"," +
            "\"result_id\":\"de\",\"title\":\"HQ captions\",\"length_s\":null,\"label\":null,\"thumbnail\":null," +
            "\"created_at\":1763901000.0,\"read\":false}";
    private static final String INBOX = "{\"unread\":3,\"items\":[" + CAPTIONS + "," + CUT + "," + SUMMARY + "," + RESEARCH + "]}";

    @Test
    public void parsesEveryResultWithItsFieldsNewestFirst() throws Exception {
        InboxList list = UtubotParser.parseInbox(INBOX);

        assertEquals(3, list.unread);
        assertEquals(4, list.items.size());

        // The backend lists newest first: captions, cut, summary, research
        InboxItem captions = list.items.get(0);
        assertEquals(4, captions.id);
        assertEquals("abcdefghijk", captions.videoId);
        assertEquals(InboxKind.CAPTIONS, captions.kind);
        assertEquals("de", captions.resultId);
        assertNull(captions.promptKey);
        assertNull(captions.label);
        assertNull(captions.thumbnail);
        assertEquals(1763901000.0, captions.createdAt, 0.0);
        assertFalse(captions.read);

        InboxItem cut = list.items.get(1);
        assertEquals(3, cut.id);
        assertEquals(InboxKind.CUT, cut.kind);
        assertEquals("cut1", cut.resultId);
        assertEquals("A video", cut.title);
        assertEquals(240, cut.lengthS);
        assertEquals("Only the demo", cut.label);
        assertEquals("https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", cut.thumbnail);

        InboxItem summary = list.items.get(2);
        assertEquals(2, summary.id);
        assertEquals(InboxKind.SUMMARY, summary.kind);
        assertEquals("kw-keep-the-demo", summary.resultId);
        assertEquals("kw-keep-the-demo", summary.promptKey);
        assertNull(summary.title);
        assertEquals(180, summary.lengthS);
        assertTrue(summary.read);

        InboxItem research = list.items.get(3);
        assertEquals(1, research.id);
        assertEquals(InboxKind.RESEARCH, research.kind);
        assertEquals("en", research.resultId);
        assertEquals(-1, research.lengthS);
        assertNull(research.thumbnail);
    }

    @Test
    public void anEmptyInboxHasNoItemsAndNoUnread() throws Exception {
        InboxList list = UtubotParser.parseInbox("{\"items\":[]}");
        assertTrue(list.items.isEmpty());
        assertEquals(0, list.unread);

        InboxList absent = UtubotParser.parseInbox("{}");
        assertTrue(absent.items.isEmpty());
        assertEquals(0, absent.unread);
    }

    @Test
    public void missingFieldsKeepTheirDefaults() throws Exception {
        InboxList list = UtubotParser.parseInbox("{\"items\":[{\"video_id\":\"a\"}]}");
        InboxItem item = list.items.get(0);

        assertEquals(0, item.id);
        assertEquals("a", item.videoId);
        assertNull(item.kind);
        assertNull(item.resultId);
        assertNull(item.promptKey);
        assertNull(item.title);
        assertEquals(-1, item.lengthS);
        assertNull(item.label);
        assertNull(item.thumbnail);
        assertEquals(0.0, item.createdAt, 0.0);
        assertFalse(item.read);
    }

    @Test
    public void itemsWithoutAVideoIdAreSkipped() throws Exception {
        InboxList list = UtubotParser.parseInbox("{\"items\":[{\"kind\":\"cut\",\"result_id\":\"cut1\"}," +
                "{\"video_id\":\"a\",\"kind\":\"summary\"}]}");
        assertEquals(1, list.items.size());
        assertEquals("a", list.items.get(0).videoId);
    }
}
