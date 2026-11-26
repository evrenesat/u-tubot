package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotChangelog.Entry;

import org.json.JSONException;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.List;
import java.util.TimeZone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotChangelogTest {
    private static final TimeZone UTC = TimeZone.getTimeZone("UTC");
    private static final String ANSWER = "{\"kind\":\"backend\",\"current\":\"0.3.9+abc\",\"entries\":["
            + "{\"kind\":\"backend\",\"version\":\"0.3.9+abc\",\"at\":1795600800.0,\"commit\":\"abc\",\"changes\":["
            + "{\"group\":\"fixes\",\"text\":\"Cuts: skip works\",\"pr\":4},"
            + "{\"group\":\"features\",\"text\":\"Captions: faster\",\"pr\":null},"
            + "{\"group\":\"other\",\"text\":\"Tidy\"},{\"group\":\"fixes\",\"text\":\"  \"}]},"
            + "{\"version\":\"\"},{\"version\":\"0.3.8+old\",\"at\":0,\"changes\":[]}]}";

    @Test
    public void parse_keepsTheOrderAndDropsEmptyRows() throws JSONException {
        List<Entry> entries = UtubotChangelog.parse(ANSWER);

        assertEquals(2, entries.size());
        assertEquals("0.3.9+abc", entries.get(0).version);
        assertEquals(1795600800000L, entries.get(0).atMs);
        assertEquals(3, entries.get(0).changes.size());
        assertEquals("0.3.8+old", entries.get(1).version);
    }

    @Test
    public void text_groupsNewFixedOther() throws JSONException {
        Entry entry = UtubotChangelog.parse(ANSWER).get(0);

        assertEquals("2026-11-25 10:00\n\nNew\n- Captions: faster\n\nFixed\n- Cuts: skip works\n\nOther\n- Tidy",
                UtubotChangelog.text(entry, UTC, "none"));
    }

    @Test
    public void text_saysWhenNothingWasListed() throws JSONException {
        Entry entry = UtubotChangelog.parse(ANSWER).get(1);

        assertEquals("No changes", UtubotChangelog.text(entry, UTC, "No changes"));
    }

    @Test
    public void title_hasTheVersionAndTime() throws JSONException {
        List<Entry> entries = UtubotChangelog.parse(ANSWER);

        assertEquals("Backend 0.3.9+abc - 2026-11-25 10:00", UtubotChangelog.title("Backend", entries.get(0), UTC));
        assertEquals("Backend 0.3.8+old", UtubotChangelog.title("Backend", entries.get(1), UTC));
    }

    @Test
    public void find_matchesTheInstalledVersion() throws JSONException {
        List<Entry> entries = UtubotChangelog.parse(ANSWER);

        assertNotNull(UtubotChangelog.find(entries, "0.3.8+old"));
        assertNull(UtubotChangelog.find(entries, "0.3.7"));
    }

    @Test
    public void isPending_onlyAfterAnUpdate() {
        assertFalse(UtubotWhatsNew.isPending("", "0.3.5"));
        assertFalse(UtubotWhatsNew.isPending("0.3.5", "0.3.5"));
        assertFalse(UtubotWhatsNew.isPending("0.3.5", ""));
        assertTrue(UtubotWhatsNew.isPending("0.3.4", "0.3.5"));
    }
}
