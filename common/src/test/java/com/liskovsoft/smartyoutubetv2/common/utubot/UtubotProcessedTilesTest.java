package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutState;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.JobState;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCaption;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The Processed section's tiles from {@code GET /v1/processed}: the item fields, its processed line with the states, the order
 * of the backend and the empty answer.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotProcessedTilesTest {
    @Test
    public void readyCaptionsCutAndSummaryBecomeOneTile() {
        Context context = RuntimeEnvironment.getApplication();
        BrowseSection section = section(context);

        ProcessedItem item = item("dQw4w9WgXcQ", "A video");
        item.thumbnail = "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg";
        item.summary = true;
        item.captions = Collections.singletonList(caption(JobState.READY));
        item.cuts = Collections.singletonList(cut(CutState.READY, "Only the demo", null));

        VideoGroup group = UtubotProcessedSection.toGroup(context, section, list(item));

        assertEquals("Processed", group.getTitle());
        assertEquals(-1, group.getPosition());
        assertEquals(VideoGroup.ACTION_REPLACE, group.getAction());
        assertEquals(1, group.getVideos().size());

        Video video = group.getVideos().get(0);
        assertEquals("dQw4w9WgXcQ", video.videoId);
        assertEquals("A video", video.title);
        assertEquals(item.thumbnail, video.cardImageUrl);
        assertEquals("HQ captions: ready • Cut ready: Only the demo • Summary ready", video.secondTitle.toString());
        assertNull(video.channelId);
    }

    @Test
    public void unfinishedCaptionAndCutSayTheirNewestState() {
        Context context = RuntimeEnvironment.getApplication();
        ProcessedItem item = item("video-one", "Still working");
        item.captions = Arrays.asList(caption(JobState.PROCESSING), caption(JobState.WAITING));
        item.cuts = Collections.singletonList(cut(CutState.BUILDING, null, "Keep the demo"));

        String text = UtubotProcessedSection.processedText(context, item);

        assertEquals("HQ captions: processing • Cut building: Keep the demo", text);
    }

    @Test
    public void everyReadyCutPresetIsNamed() {
        Context context = RuntimeEnvironment.getApplication();
        ProcessedItem item = item("video-two", "Two cuts");
        item.cuts = Arrays.asList(cut(CutState.READY, "Only the demo", null), cut(CutState.READY, "Short version", null));

        assertEquals("Cut ready: Only the demo, Short version", UtubotProcessedSection.processedText(context, item));
    }

    @Test
    public void aFailedCutAndAHiddenSummaryStateHaveNoSummaryPart() {
        Context context = RuntimeEnvironment.getApplication();
        ProcessedItem item = item("video-three", "A failed cut");
        item.cuts = Collections.singletonList(cut(CutState.FAILED, "Only the demo", null));

        assertEquals("Cut failed: Only the demo", UtubotProcessedSection.processedText(context, item));
    }

    @Test
    public void theTilesFollowTheBackendsNewestFirstOrderAndAnEmptyAnswerHasNoVideo() {
        Context context = RuntimeEnvironment.getApplication();
        BrowseSection section = section(context);
        ProcessedItem newest = item("newest", "Newest");
        ProcessedItem older = item("older", "Older");
        newest.updatedAt = 20;
        older.updatedAt = 10;

        VideoGroup group = UtubotProcessedSection.toGroup(context, section, list(newest, older));

        assertEquals(Arrays.asList("newest", "older"), videoIds(group));

        VideoGroup empty = UtubotProcessedSection.toGroup(context, section, new ProcessedList());
        assertTrue(empty.isEmpty());
        assertEquals("Processed", empty.getTitle());
    }

    private static BrowseSection section(Context context) {
        return new BrowseSection(UtubotProcessedSection.ID, context.getString(R.string.utubot_processed_title), BrowseSection.TYPE_GRID, 0);
    }

    private static ProcessedList list(ProcessedItem... items) {
        ProcessedList list = new ProcessedList();
        list.videos = new ArrayList<>(Arrays.asList(items));
        return list;
    }

    private static ProcessedItem item(String videoId, String title) {
        ProcessedItem item = new ProcessedItem();
        item.videoId = videoId;
        item.title = title;
        return item;
    }

    private static ProcessedCaption caption(String state) {
        ProcessedCaption caption = new ProcessedCaption();
        caption.jobId = "job";
        caption.state = state;
        return caption;
    }

    private static ProcessedCut cut(String state, String presetLabel, String prompt) {
        ProcessedCut cut = new ProcessedCut();
        cut.requestId = "request";
        cut.state = state;
        cut.presetLabel = presetLabel;
        cut.prompt = prompt;
        return cut;
    }

    private static java.util.List<String> videoIds(VideoGroup group) {
        java.util.List<String> ids = new ArrayList<>();

        for (Video video : group.getVideos()) {
            ids.add(video.videoId);
        }

        return ids;
    }
}
