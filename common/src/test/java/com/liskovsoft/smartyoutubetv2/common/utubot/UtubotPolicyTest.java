package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.misc.AiSListManager;
import com.liskovsoft.smartyoutubetv2.common.prefs.AiSListFilterData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Flag;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPolicy.Decision;

import org.junit.Test;

import java.util.Collections;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

public class UtubotPolicyTest {
    private static Verdict verdict(String status, String action) {
        Verdict verdict = new Verdict();
        verdict.videoId = "v";
        verdict.status = status;
        verdict.action = action;
        return verdict;
    }

    @Test
    public void hideIsHidden() {
        assertEquals(Decision.HIDE, UtubotPolicy.decide(verdict("ready", "hide"), false));
    }

    @Test
    public void markOnlyTurnsHideIntoMark() {
        assertEquals(Decision.MARK, UtubotPolicy.decide(verdict("ready", "hide"), true));
    }

    @Test
    public void markStaysMark() {
        assertEquals(Decision.MARK, UtubotPolicy.decide(verdict("ready", "mark"), false));
        assertEquals(Decision.MARK, UtubotPolicy.decide(verdict("ready", "mark"), true));
    }

    @Test
    public void noneAndPendingAndMissingAreShown() {
        assertEquals(Decision.SHOW, UtubotPolicy.decide(verdict("ready", "none"), false));
        assertEquals(Decision.SHOW, UtubotPolicy.decide(verdict("pending", "hide"), false));
        assertEquals(Decision.SHOW, UtubotPolicy.decide(null, false));
        assertEquals(Decision.SHOW, UtubotPolicy.decide(verdict("ready", "unknown-action"), false));
    }

    @Test
    public void markLabelFallsBackToFlagThenBareMarker() {
        Verdict withLabel = verdict("ready", "mark");
        withLabel.markLabel = "Clickbait · 12m≈2m";
        assertEquals("Clickbait · 12m≈2m", UtubotPolicy.markLabel(withLabel));

        Verdict withFlag = verdict("ready", "mark");
        Flag flag = new Flag();
        flag.label = "Inflated";
        withFlag.flags = Collections.singletonList(flag);
        assertEquals("Inflated", UtubotPolicy.markLabel(withFlag));

        assertEquals(UtubotPolicy.FALLBACK_MARK_LABEL, UtubotPolicy.markLabel(verdict("ready", "mark")));
    }

    @Test
    public void sectionsMapToTheContractNames() {
        assertEquals("home", UtubotPolicy.sectionName(AiSListFilterData.SECTION_HOME));
        assertEquals("subscriptions", UtubotPolicy.sectionName(AiSListFilterData.SECTION_SUBSCRIPTIONS));
        assertEquals("subscriptions", UtubotPolicy.sectionName(AiSListFilterData.SECTION_CHANNEL_GROUPS));
        assertEquals("search", UtubotPolicy.sectionName(AiSListFilterData.SECTION_SEARCH));
        assertEquals("channel", UtubotPolicy.sectionName(AiSListManager.SECTION_CHANNEL_PAGE));
        assertEquals("other", UtubotPolicy.sectionName(AiSListFilterData.SECTION_SUGGESTIONS));
        assertNull(UtubotPolicy.sectionName(AiSListFilterData.SECTION_HISTORY));
        assertNull(UtubotPolicy.sectionName(AiSListFilterData.SECTION_PLAYLISTS));
        assertNull(UtubotPolicy.sectionName(AiSListFilterData.SECTION_WATCH_LATER));
    }

    @Test
    public void answerLabelIsNullWithoutAnswer() {
        Verdict verdict = verdict("ready", "none");
        assertNull(UtubotPolicy.answerLabel(verdict));
        verdict.answerShort = "";
        assertNull(UtubotPolicy.answerLabel(verdict));
        verdict.answerShort = "Yes, since v3.";
        assertEquals("Yes, since v3.", UtubotPolicy.answerLabel(verdict));
        assertNull(UtubotPolicy.answerLabel(null));
    }
}
