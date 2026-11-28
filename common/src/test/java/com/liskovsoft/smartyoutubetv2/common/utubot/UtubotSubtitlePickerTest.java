package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.Choice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.External;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSubtitlePicker.Embedded;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSubtitlePicker.Entry;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotSubtitlePickerTest {
    private static final List<Embedded> FILE = Arrays.asList(
            new Embedded("f1", "fra", "", null), new Embedded("f2", "en", "SDH", null), new Embedded("f3", "tr", "Forced", null));
    private static final List<External> NET = Arrays.asList(
            new External("n1", "tur", "Movie.1080p.BluRay-GROUP.srt", 0.9, true), new External("n2", "eng", "Movie.720p.srt", 0.4, false));

    private static List<Entry> build(Choice current, String viewer) {
        return UtubotSubtitlePicker.build(FILE, NET, viewer, current, "Off", "File: ", "Net: ", "best match");
    }

    private static String ids(List<Entry> entries) {
        StringBuilder out = new StringBuilder();

        for (Entry entry : entries) {
            out.append(entry.id.isEmpty() ? "off" : entry.id).append(' ');
        }

        return out.toString().trim();
    }

    @Test
    public void offThenTheFilesTracksThenTheInternetOnesInTheBackendsOrder() {
        assertEquals("off f3 f2 f1 n1 n2", ids(build(null, "tr")));
    }

    @Test
    public void theFilesTracksStartWithTheViewersLanguageThenEnglish() {
        assertEquals("off f2 f1 f3 n1 n2", ids(build(null, "en")));
        assertEquals("f2", build(null, "").get(1).id); // no language: English first
    }

    @Test
    public void theFirstInternetEntryIsTheBestMatchAndSaysSo() {
        List<Entry> entries = build(null, "tr");
        Entry first = entries.get(4);
        Entry second = entries.get(5);

        assertTrue(first.best);
        assertTrue(first.label, first.label.contains("(best match)") && first.label.startsWith("Net: Turkish"));
        assertFalse(second.best);
        assertFalse(second.label.contains("best match"));
    }

    @Test
    public void exactlyTheChoiceInUseIsMarked() {
        assertTrue(build(null, "tr").get(0).selected);
        List<Entry> embedded = build(new Choice(Choice.EMBEDDED, "f2", "en", 0), "tr");
        assertEquals(1, embedded.stream().filter(e -> e.selected).count());
        assertTrue(embedded.stream().filter(e -> e.selected).findFirst().get().id.equals("f2"));
        List<Entry> external = build(new Choice(Choice.EXTERNAL, "n2", "eng", 500), "tr");
        assertTrue(external.get(5).selected && !external.get(0).selected);
    }

    @Test
    public void languageCodesOfTwoAndThreeLettersMatchAndAreNamed() {
        assertEquals("tr", UtubotSubtitlePicker.normalize("tur"));
        assertEquals("pt", UtubotSubtitlePicker.normalize("pt-BR"));
        assertEquals("en", UtubotSubtitlePicker.normalize("ENG"));
        assertEquals("English", UtubotSubtitlePicker.languageName("eng"));
        assertEquals("", UtubotSubtitlePicker.languageName(null));
    }

    @Test
    public void aTitleThatOnlyRepeatsTheLanguageIsLeftOut() {
        List<Entry> entries = UtubotSubtitlePicker.build(Arrays.asList(new Embedded("a", "en", "en", null), new Embedded("b", "tr", "Forced", null)),
                Collections.emptyList(), "en", null, "Off", "F: ", "N: ", "best");

        assertEquals("F: English", entries.get(1).label);
        assertEquals("F: Turkish - Forced", entries.get(2).label);
    }

    @Test
    public void withNothingElseThePickerIsJustOff() {
        List<Entry> entries = UtubotSubtitlePicker.build(Collections.emptyList(), Collections.emptyList(), "en", null, "Off", "F: ", "N: ", "best");

        assertEquals(1, entries.size());
        assertTrue(entries.get(0).selected);
    }

    @Test
    public void rememberedChoiceFindsTheSameLanguageInTheNextFile() {
        Choice french = new Choice(Choice.EMBEDDED, "other", "fr", 0);
        assertEquals("f1", UtubotSubtitlePicker.rememberedEmbedded(FILE, french).id);
        assertEquals("f3", UtubotSubtitlePicker.rememberedEmbedded(FILE, new Choice(Choice.EMBEDDED, "", "tur", 0)).id);
        org.junit.Assert.assertNull(UtubotSubtitlePicker.rememberedEmbedded(FILE, new Choice(Choice.EMBEDDED, "", "de", 0)));
        org.junit.Assert.assertNull(UtubotSubtitlePicker.rememberedEmbedded(FILE, new Choice(Choice.OFF, "", "", 0)));
        org.junit.Assert.assertNull(UtubotSubtitlePicker.rememberedEmbedded(FILE, null));
    }

    @Test
    public void rememberedInternetChoiceTakesTheBestMatchOfItsLanguage() {
        assertEquals("n2", UtubotSubtitlePicker.rememberedExternal(NET, new Choice(Choice.EXTERNAL, "", "en", 0)).id);
        org.junit.Assert.assertNull(UtubotSubtitlePicker.rememberedExternal(NET, new Choice(Choice.EXTERNAL, "", "de", 0)));
        org.junit.Assert.assertNull(UtubotSubtitlePicker.rememberedExternal(NET, new Choice(Choice.EMBEDDED, "", "en", 0)));
    }
}
