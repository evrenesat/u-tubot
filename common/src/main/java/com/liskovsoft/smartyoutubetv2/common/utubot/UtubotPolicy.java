package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.prefs.AiSListFilterData;
import com.liskovsoft.smartyoutubetv2.common.misc.AiSListManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Flag;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

/**
 * What a card does with a verdict, and which sections are assessed. The backend applies the user's policy (the verdict's action),
 * the app only adds its own mark-only switch.
 */
public final class UtubotPolicy {
    public static final int MARK_COLOR = 0xFFD84315;
    public static final String FALLBACK_MARK_LABEL = "AI";
    public static final String SECTION_HOME = "home";
    public static final String SECTION_SUBSCRIPTIONS = "subscriptions";
    public static final String SECTION_SEARCH = "search";
    public static final String SECTION_CHANNEL = "channel";
    public static final String SECTION_OTHER = "other";

    public enum Decision {
        SHOW, MARK, HIDE
    }

    private UtubotPolicy() {
    }

    /**
     * @param verdict null or not ready: the card is shown as it is
     * @param markOnly the user never wants a card hidden
     */
    public static Decision decide(@Nullable Verdict verdict, boolean markOnly) {
        if (verdict == null || !verdict.isReady()) {
            return Decision.SHOW;
        }

        if (UtubotModels.ACTION_HIDE.equals(verdict.action)) {
            return markOnly ? Decision.MARK : Decision.HIDE;
        }

        return UtubotModels.ACTION_MARK.equals(verdict.action) ? Decision.MARK : Decision.SHOW;
    }

    /**
     * The short text of the card mark: the backend's label, else the first flag's, else a bare marker
     */
    public static String markLabel(Verdict verdict) {
        if (verdict.markLabel != null && !verdict.markLabel.isEmpty()) {
            return verdict.markLabel;
        }

        for (Flag flag : verdict.flags) {
            if (flag.label != null && !flag.label.isEmpty()) {
                return flag.label;
            }
        }

        return FALLBACK_MARK_LABEL;
    }

    /**
     * @param aiSListSection the section AiSListManager knows a group by (see VideoGroup.getAiSListSection)
     * @return the contract's section name or null when the section isn't assessed (History, playlists, Watch later and channel lists)
     */
    @Nullable
    public static String sectionName(int aiSListSection) {
        switch (aiSListSection) {
            case AiSListFilterData.SECTION_HOME:
                return SECTION_HOME;
            case AiSListFilterData.SECTION_SUBSCRIPTIONS:
            case AiSListFilterData.SECTION_CHANNEL_GROUPS:
                return SECTION_SUBSCRIPTIONS;
            case AiSListFilterData.SECTION_SEARCH:
                return SECTION_SEARCH;
            case AiSListManager.SECTION_CHANNEL_PAGE:
                return SECTION_CHANNEL;
            case AiSListFilterData.SECTION_SUGGESTIONS:
                return SECTION_OTHER;
            default:
                return null;
        }
    }

    /**
     * The text of the answer in a menu label, e.g. "Yes, since v3."
     */
    @Nullable
    public static String answerLabel(@Nullable Verdict verdict) {
        return verdict != null && verdict.answerShort != null && !verdict.answerShort.isEmpty() ? verdict.answerShort : null;
    }
}
