package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxKind;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.Collections;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The Inbox section's tiles (u-tubot #160): each result is one tile with what it is and, for research and captions, its language, and
 * only the tiles of the Inbox section are inbox cards.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotInboxSectionTest {
    private final Context mContext = RuntimeEnvironment.getApplication();

    @Test
    public void theTileCarriesTheResultWhatItIsAndItsLanguage() {
        InboxItem cut = item(InboxKind.CUT, "dQw4w9WgXcQ", "cut1");
        cut.id = 1;
        cut.title = "A video";
        cut.label = "Only the demo";
        cut.thumbnail = "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg";

        Video video = UtubotInboxSection.toVideo(mContext, cut);

        assertEquals("dQw4w9WgXcQ", video.videoId);
        assertEquals("A video", video.title);
        assertEquals("https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", video.cardImageUrl);
        assertEquals(InboxKind.CUT, video.inboxKind);
        assertEquals(1L, video.inboxId);
        assertEquals("Director's cut · Only the demo", video.secondTitle.toString());
    }

    @Test
    public void aResultWithoutADetailShowsOnlyWhatItIs() {
        assertEquals("Director's cut", UtubotInboxSection.resultLabel(mContext, item(InboxKind.CUT, "a", "cut1")));
        assertEquals("Research", UtubotInboxSection.resultLabel(mContext, item(InboxKind.RESEARCH, "a", null)));
        assertEquals("HQ captions", UtubotInboxSection.resultLabel(mContext, item(InboxKind.CAPTIONS, "a", null)));
    }

    @Test
    public void aSummaryShowsItsPromptKeyWhenItHasNoLabel() {
        InboxItem summary = item(InboxKind.SUMMARY, "a", "keep-the-demo");
        assertNull(summary.label);

        assertEquals("Summary · keep-the-demo", UtubotInboxSection.resultLabel(mContext, summary));
    }

    @Test
    public void theTileShowsTheVideoLengthLastWhenKnown() {
        InboxItem cut = item(InboxKind.CUT, "dQw4w9WgXcQ", "cut1");
        cut.title = "A video";
        cut.label = "Only the demo";
        cut.lengthS = 302;

        assertEquals("Director's cut · Only the demo · 5:02", UtubotInboxSection.resultLabel(mContext, cut));
    }

    @Test
    public void theLengthPastAnHourIsHoursMinutesSeconds() {
        InboxItem summary = item(InboxKind.SUMMARY, "a", "keep-the-demo");
        summary.lengthS = 3_723;

        assertEquals("Summary · keep-the-demo · 1:02:03", UtubotInboxSection.resultLabel(mContext, summary));
    }

    @Test
    public void anUnknownLengthKeepsTheLabelWithoutTrailingSeparator() {
        assertEquals("Director's cut", UtubotInboxSection.resultLabel(mContext, item(InboxKind.CUT, "a", "cut1")));
    }

    @Test
    public void researchAndCaptionsShowTheirLanguage() {
        assertEquals("Research · English", UtubotInboxSection.resultLabel(mContext, item(InboxKind.RESEARCH, "a", "en")));
        assertEquals("Research · German", UtubotInboxSection.resultLabel(mContext, item(InboxKind.RESEARCH, "a", "de")));
        assertEquals("HQ captions · Turkish", UtubotInboxSection.resultLabel(mContext, item(InboxKind.CAPTIONS, "a", "tr")));
    }

    @Test
    public void anUnknownKindShowsItsTitleOrVideoId() {
        InboxItem unknown = item("weird", "a", "r1");
        unknown.title = "Something";
        assertEquals("Something", UtubotInboxSection.resultLabel(mContext, unknown));

        unknown.title = null;
        assertEquals("a", UtubotInboxSection.resultLabel(mContext, unknown));
    }

    @Test
    public void theTileTitleFallsBackToTheVideoId() {
        InboxItem item = item(InboxKind.CUT, "dQw4w9WgXcQ", "cut1");
        item.title = null;

        assertEquals("dQw4w9WgXcQ", UtubotInboxSection.toVideo(mContext, item).title);
    }

    @Test
    public void theGroupCarriesTheInboxSectionAndOneTilePerResult() {
        BrowseSection section = new BrowseSection(UtubotInboxSection.ID, mContext.getString(R.string.utubot_inbox_title),
                BrowseSection.TYPE_GRID, 0);
        InboxList list = new InboxList();
        list.items = Collections.singletonList(item(InboxKind.CUT, "dQw4w9WgXcQ", "cut1"));

        VideoGroup group = UtubotInboxSection.toGroup(mContext, section, list);

        assertEquals(UtubotInboxSection.ID, group.getSection().getId());
        assertEquals(mContext.getString(R.string.utubot_inbox_title), group.getTitle());
        assertEquals(1, group.getVideos().size());
    }

    @Test
    public void onlyTheInboxTilesAreInboxCards() {
        BrowseSection inbox = new BrowseSection(UtubotInboxSection.ID, "Inbox", BrowseSection.TYPE_GRID, 0);
        VideoGroup group = UtubotInboxSection.toGroup(mContext, inbox, inboxList());

        assertTrue(UtubotInboxOpen.isInbox(group.getVideos().get(0)));
        assertFalse(UtubotInboxOpen.isInbox(new Video()));
        assertFalse(UtubotInboxOpen.isInbox(null));
    }

    private InboxList inboxList() {
        InboxList list = new InboxList();
        list.items = Collections.singletonList(item(InboxKind.CUT, "dQw4w9WgXcQ", "cut1"));
        return list;
    }

    private static InboxItem item(String kind, String videoId, String resultId) {
        InboxItem item = new InboxItem();
        item.kind = kind;
        item.videoId = videoId;
        item.resultId = resultId;
        return item;
    }
}
