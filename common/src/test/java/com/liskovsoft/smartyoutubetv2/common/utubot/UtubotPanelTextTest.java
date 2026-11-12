package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

public class UtubotPanelTextTest {
    @Test
    public void aFirstLineWithTheArrowIsTheLead() {
        UtubotPanelText.Split split = UtubotPanelText.split("→ Yes, since v3.\nIt landed in the March release.\nSecond point.");

        assertEquals("→ Yes, since v3.", split.lead);
        assertEquals("It landed in the March release.\nSecond point.", split.rest);
    }

    @Test
    public void aTextWithoutTheArrowHasNoLead() {
        UtubotPanelText.Split split = UtubotPanelText.split("It landed in the March release.\n→ not first");

        assertNull(split.lead);
        assertEquals("It landed in the March release.\n→ not first", split.rest);
    }

    @Test
    public void aLeadAloneAndLeadingSpace() {
        assertEquals("→ Yes.", UtubotPanelText.split("  \n→ Yes.").lead);
        assertEquals("", UtubotPanelText.split("→ Yes.").rest);
    }

    @Test
    public void nullAndEmptyTexts() {
        assertNull(UtubotPanelText.split(null).lead);
        assertEquals("", UtubotPanelText.split(null).rest);
        assertEquals("", UtubotPanelText.split("").rest);
    }
}
