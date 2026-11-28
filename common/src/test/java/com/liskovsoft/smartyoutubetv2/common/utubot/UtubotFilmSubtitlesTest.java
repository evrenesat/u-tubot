package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.Choice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.External;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmSubtitlesTest {
    @Test
    public void theBackendsListIsReadInItsOrderAndAnEntryWithoutAnIdIsDropped() throws Exception {
        String json = "{\"subtitles\":[{\"id\":\"a\",\"lang\":\"tur\",\"name\":\"x.srt\",\"score\":0.9,\"best\":true},{\"lang\":\"eng\"},"
                + "{\"id\":\"b\",\"lang\":\"eng\",\"name\":\"y.srt\",\"score\":0.5}]}";

        List<External> list = UtubotFilmSubtitles.parse(json);

        assertEquals(2, list.size());
        assertEquals("a", list.get(0).id);
        assertTrue(list.get(0).best);
        assertEquals("eng", list.get(1).lang);
        assertEquals(0, UtubotFilmSubtitles.parse("{}").size());
    }

    @Test
    public void aDelayMovesEveryCueAndNeverBelowZero() {
        String vtt = "WEBVTT\n\n00:00:01.500 --> 00:00:03.250\nHello\n\n1:01:01.000 --> 1:01:02.000\nLate\n";

        String later = UtubotFilmSubtitles.shiftVtt(vtt, 2_000);
        String earlier = UtubotFilmSubtitles.shiftVtt(vtt, -2_000);

        assertTrue(later, later.contains("00:00:03.500 --> 00:00:05.250"));
        assertTrue(later, later.contains("01:01:03.000 --> 01:01:04.000"));
        assertTrue(earlier, earlier.contains("00:00:00.000 --> 00:00:01.250"));
        assertTrue(later.contains("Hello") && later.startsWith("WEBVTT"));
        assertEquals(vtt, UtubotFilmSubtitles.shiftVtt(vtt, 0));
    }

    @Test
    public void aLineOfTextWithATimeLikeNumberIsNotShifted() {
        String vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nIt is 10:20:30.400 now\n";

        assertTrue(UtubotFilmSubtitles.shiftVtt(vtt, 1_000).contains("It is 10:20:30.400 now"));
    }

    @Test
    public void theChoiceSurvivesStorageAndTheDelayIsBounded() {
        Choice choice = new Choice(Choice.EXTERNAL, "sub-1", "eng", 1_250);

        Choice back = Choice.decode(choice.encode());

        assertNotNull(back);
        assertEquals("external", back.kind);
        assertEquals("sub-1", back.id);
        assertEquals(1_250, back.delayMs);
        assertEquals(UtubotFilmSubtitles.DELAY_LIMIT_MS, new Choice(Choice.EXTERNAL, "x", "", 10 * UtubotFilmSubtitles.DELAY_LIMIT_MS).delayMs);
        assertNull(Choice.decode("nonsense"));
        assertNull(Choice.decode("external\tx\ten\tNaN"));
        assertNull(Choice.decode(null));
    }

    @Test
    public void lastChoiceIsGlobalAndATitlesOwnChoiceStaysSeparate() {
        android.content.Context context = org.robolectric.RuntimeEnvironment.getApplication();
        UtubotFilmSubtitles.Store store = new UtubotFilmSubtitles.Store(context);
        org.junit.Assert.assertNull(store.getLast());

        store.set("tt1:1:1", new Choice(Choice.EXTERNAL, "n1", "tr", 1500));
        store.setLast(new Choice(Choice.EXTERNAL, "n1", "tr", 1500));
        assertEquals("tr", store.getLast().lang);
        assertEquals(Choice.EXTERNAL, store.getLast().kind);
        assertEquals(0, store.getLast().delayMs); // the delay belongs to the title
        org.junit.Assert.assertNull(store.get("tt1:1:2")); // the next episode has no choice of its own, so the last one applies

        store.set("tt1:1:2", new Choice(Choice.OFF, "", "", 0)); // its own choice wins and does not need the last one
        assertEquals(Choice.OFF, store.get("tt1:1:2").kind);

        store.setLast(new Choice(Choice.OFF, "", "", 0));
        assertEquals(Choice.OFF, store.getLast().kind);
    }
}
