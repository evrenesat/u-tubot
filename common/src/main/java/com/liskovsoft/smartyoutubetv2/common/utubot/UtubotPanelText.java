package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

/**
 * The text of a glance summary: a first line that starts with "→ " is the answer to the question of the title, and is shown
 * emphasised
 */
public final class UtubotPanelText {
    public static final String LEAD_MARK = "→ ";

    public static final class Split {
        /** The emphasised first line, null when the text has none */
        @Nullable public final String lead;
        /** The rest of the text, without the line break after the lead */
        public final String rest;

        Split(@Nullable String lead, String rest) {
            this.lead = lead;
            this.rest = rest;
        }
    }

    private UtubotPanelText() {
    }

    public static Split split(@Nullable String text) {
        if (text == null) {
            return new Split(null, "");
        }

        String trimmed = withoutLeadingSpace(text);

        if (!trimmed.startsWith(LEAD_MARK)) {
            return new Split(null, text);
        }

        int lineEnd = trimmed.indexOf('\n');

        if (lineEnd < 0) {
            return new Split(trimmed.trim(), "");
        }

        return new Split(trimmed.substring(0, lineEnd).trim(), withoutLeadingSpace(trimmed.substring(lineEnd + 1)));
    }

    private static String withoutLeadingSpace(String text) {
        int start = 0;

        while (start < text.length() && Character.isWhitespace(text.charAt(start))) {
            start++;
        }

        return text.substring(start);
    }
}
