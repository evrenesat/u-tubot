package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Application;
import android.content.Context;
import android.graphics.Rect;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel;
import com.liskovsoft.smartyoutubetv2.tv.R;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import java.util.ArrayList;

import io.reactivex.Observable;
import io.reactivex.schedulers.Schedulers;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

/**
 * The passive panel is a visitor of the screen: a corner strip below the top bar, never a window of its own, never focusable, and
 * whatever it does (comes, waits, shows a long summary, goes) leaves the screen's own views where, how big and how visible they were.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
// The app's Conscrypt has no native library here, and no TLS is used
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotPanelViewTest {
    private static final int SCREEN_WIDTH = 1920;
    private static final int SCREEN_HEIGHT = 1080;
    private static final int TOP_BAR_HEIGHT = 162;
    private static final int PERCENT = 100;
    private static final String LONG_TITLE = "A very long title that goes on and on and on and on and on and on and on and on and on and on and on and on";

    private Context mContext;
    private FrameLayout mScreen;
    private View mGrid;
    private View mTopBar;
    private UtubotPanelView mPanel;
    private UtubotPanelModel mModel;
    private StubSource mSource;
    private int mMargin;
    private int mPercent;

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.getApplication();
        mContext.setTheme(androidx.appcompat.R.style.Theme_AppCompat);
        mMargin = mContext.getResources().getDimensionPixelSize(R.dimen.utubot_panel_margin);
        mPercent = mContext.getResources().getInteger(R.integer.utubot_panel_width_percent);

        // What an activity's content looks like: the screen's own views first, the panel added after them
        mScreen = new FrameLayout(mContext);
        mGrid = new View(mContext);
        mScreen.addView(mGrid, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        mTopBar = new View(mContext);
        mScreen.addView(mTopBar, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, TOP_BAR_HEIGHT, Gravity.TOP));

        mPanel = new UtubotPanelView(mContext);
        mScreen.addView(mPanel, UtubotPanelView.layoutParams(mContext, SCREEN_WIDTH, TOP_BAR_HEIGHT));
        mSource = new StubSource();
        mModel = new UtubotPanelModel(mSource, UtubotPanelModel.Mode.PANEL, mPanel::bind, Schedulers.trampoline());
        layOut();
    }

    private void layOut() {
        mScreen.measure(View.MeasureSpec.makeMeasureSpec(SCREEN_WIDTH, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(SCREEN_HEIGHT, View.MeasureSpec.EXACTLY));
        mScreen.layout(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT);
    }

    private static Rect bounds(View view) {
        return new Rect(view.getLeft(), view.getTop(), view.getRight(), view.getBottom());
    }

    private static Video video(String title) {
        Video video = new Video();
        video.videoId = "aaaaaaaaaaa";
        video.title = title;

        return video;
    }

    private static final class StubSource implements UtubotPanelModel.Source {
        String text = "→ Yes.\nLine two.\nLine three.";
        /** What the backend answers instead of a ready summary */
        @Nullable Summary answer;

        @Nullable
        @Override
        public String getSessionPrompt() {
            return null;
        }

        @Override
        public void setSessionPrompt(@Nullable String key) {
        }

        @Override
        public Observable<PromptList> promptsObserve(boolean forceReload) {
            PromptList list = new PromptList();
            list.panelDefaultKey = "builtin/glance";
            PromptSet set = new PromptSet();
            Prompt prompt = new Prompt();
            prompt.key = "builtin/glance";
            prompt.label = "Glance";
            set.prompts.add(prompt);
            list.sets.add(set);

            return Observable.just(list);
        }

        @Override
        public Observable<Summary> summaryObserve(Video video, @Nullable String promptKey) {
            if (answer != null) {
                return Observable.just(answer);
            }

            Summary summary = new Summary();
            summary.status = "ready";
            summary.text = text;

            return Observable.just(summary);
        }

        @Override
        public Observable<Transcript> transcribeObserve(Video video) {
            return Observable.just(new Transcript());
        }

        @Override
        public Observable<Transcript> transcriptObserve(String videoId) {
            return Observable.just(new Transcript());
        }
    }

    @Test
    public void itStartsGoneAndNeverTakesTheFocusOrAKey() {
        assertEquals(View.GONE, mPanel.getVisibility());
        assertFalse(mPanel.isFocusable());
        assertFalse(mPanel.isFocusableInTouchMode());
        assertFalse(mPanel.isClickable());
        assertEquals(ViewGroup.FOCUS_BLOCK_DESCENDANTS, mPanel.getDescendantFocusability());
        assertNoFocusableViews(mPanel);

        mModel.show(video("Title"));
        mPanel.setVisibility(View.VISIBLE);

        assertNoFocusableViews(mPanel);
        ArrayList<View> focusables = new ArrayList<>();
        mScreen.addFocusables(focusables, View.FOCUS_DOWN);
        assertFalse("the panel offers itself to the focus search", focusables.contains(mPanel));
    }

    private static void assertNoFocusableViews(View view) {
        assertFalse(view.getClass().getSimpleName() + " is focusable", view.isFocusable());

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;

            for (int i = 0; i < group.getChildCount(); i++) {
                assertNoFocusableViews(group.getChildAt(i));
            }
        }
    }

    @Test
    public void itTakesOnlyTheRightStripBelowTheTopBar() {
        FrameLayout.LayoutParams params = UtubotPanelView.layoutParams(mContext, SCREEN_WIDTH, TOP_BAR_HEIGHT);

        assertNotEquals("the panel must not span the parent's width", ViewGroup.LayoutParams.MATCH_PARENT, params.width);
        assertEquals("the panel is as high as its lines, never the parent's height", ViewGroup.LayoutParams.WRAP_CONTENT, params.height);
        assertEquals(Gravity.BOTTOM | Gravity.END, params.gravity);
        assertEquals(TOP_BAR_HEIGHT + mMargin, params.topMargin);
        // The strip, margin included, is the configured share of the width
        assertEquals(SCREEN_WIDTH * mPercent / PERCENT, params.width + params.rightMargin);
    }

    @Test
    public void aWideScreenOrNoTopBarStillKeepsTheStrip() {
        FrameLayout.LayoutParams params = UtubotPanelView.layoutParams(mContext, 3840, 0);

        assertEquals(3840 * mPercent / PERCENT, params.width + params.rightMargin);
        assertEquals(mMargin, params.topMargin);
        assertEquals(0, UtubotPanelView.layoutParams(mContext, 0, -5).width);
        assertEquals(mMargin, UtubotPanelView.layoutParams(mContext, 0, -5).topMargin);
    }

    @Test
    public void shownWaitingLoadingAndReadyItStaysInItsCornerStrip() {
        mModel.waitFor(video(LONG_TITLE));
        mPanel.setVisibility(View.VISIBLE);
        layOut();
        assertInCorner();

        mSource.text = longText();
        mModel.show(video(LONG_TITLE));
        layOut();
        assertInCorner();
    }

    private static String longText() {
        StringBuilder text = new StringBuilder("→ ");

        for (int i = 0; i < 400; i++) {
            text.append("word ");
        }

        return text.toString();
    }

    private void assertInCorner() {
        Rect panel = bounds(mPanel);

        assertTrue("the panel is on the right strip: " + panel, panel.left >= SCREEN_WIDTH - SCREEN_WIDTH * mPercent / PERCENT);
        assertTrue("the panel is below the top bar: " + panel, panel.top >= TOP_BAR_HEIGHT);
        assertTrue("the panel is inside the screen: " + panel, panel.right <= SCREEN_WIDTH && panel.bottom <= SCREEN_HEIGHT);
    }

    @Test
    public void aLongSummaryNeverReachesTheTopBar() {
        mSource.text = longText();
        mPanel.setVisibility(View.VISIBLE);
        mModel.show(video(LONG_TITLE));
        layOut();

        assertInCorner();
        assertTrue(mPanel.getHeight() <= SCREEN_HEIGHT - TOP_BAR_HEIGHT - 2 * mMargin);
    }

    @Test
    public void theScreensOwnViewsAreLeftAsTheyWere() {
        Rect grid = bounds(mGrid);
        Rect topBar = bounds(mTopBar);
        float gridAlpha = mGrid.getAlpha();
        int gridVisibility = mGrid.getVisibility();

        mModel.waitFor(video(LONG_TITLE));
        mPanel.setVisibility(View.VISIBLE);
        layOut();
        assertScreenUntouched(grid, topBar, gridAlpha, gridVisibility);

        mModel.show(video(LONG_TITLE));
        layOut();
        assertScreenUntouched(grid, topBar, gridAlpha, gridVisibility);

        mPanel.setVisibility(View.GONE);
        mModel.dispose();
        layOut();
        assertScreenUntouched(grid, topBar, gridAlpha, gridVisibility);
    }

    private void assertScreenUntouched(Rect grid, Rect topBar, float gridAlpha, int gridVisibility) {
        assertEquals(grid, bounds(mGrid));
        assertEquals(topBar, bounds(mTopBar));
        assertEquals(gridAlpha, mGrid.getAlpha(), 0f);
        assertEquals(gridVisibility, mGrid.getVisibility());
        assertEquals(1f, mTopBar.getAlpha(), 0f);
        assertEquals(View.VISIBLE, mTopBar.getVisibility());
        assertEquals("the panel is added after the screen's views, never replacing or moving them", 2, mScreen.indexOfChild(mPanel));
        assertEquals(3, mScreen.getChildCount());
    }

    @Test
    public void thePanelIsNotAWindow() {
        // A plain view of the content: no dialog or popup window, nothing that dims what is under it
        assertEquals(mScreen, mPanel.getParent());
        assertTrue(mPanel instanceof View);
        assertEquals(1f, mPanel.getAlpha(), 0f);
        assertTrue(mPanel.getBackground() != null);
    }

    private static Summary answer(String status, String transcriptStatus) {
        Summary summary = new Summary();
        summary.status = status;
        summary.transcriptStatus = transcriptStatus;

        return summary;
    }

    private String shownText() {
        StringBuilder text = new StringBuilder();
        collectText(mPanel, text);

        return text.toString();
    }

    private static void collectText(View view, StringBuilder text) {
        if (view instanceof TextView) {
            text.append(((TextView) view).getText()).append('\n');
        }

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;

            for (int i = 0; i < group.getChildCount(); i++) {
                collectText(group.getChildAt(i), text);
            }
        }
    }

    @Test
    public void aVideoWithoutCaptionsShowsTheServersMessage() {
        mSource.answer = answer("needs_transcript", "none");
        mSource.answer.canTranscribe = true;
        mSource.answer.message = "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~90 s)?";

        mModel.show(video("Title"));

        assertTrue(shownText().contains("Captions are temporarily unavailable from YouTube; transcribe the audio instead (~90 s)?"));
        assertFalse(shownText().contains("press Info to transcribe"));
    }

    @Test
    public void aVideoWithoutCaptionsAndWithoutAMessageShowsTheAppsOwnWords() {
        mSource.answer = answer("needs_transcript", "none");
        mSource.answer.canTranscribe = true;

        mModel.show(video("Title"));

        assertTrue(shownText().contains("No captions — press Info to transcribe"));
    }

    @Test
    public void aTranscriptionTheServerStartedShowsItsProgressAndEstimateWithoutAskingForAnything() {
        mSource.answer = answer("pending", "transcribing");
        mSource.answer.progressPercent = 35;
        mSource.answer.estimateSec = 240;

        mModel.show(video("Title"));

        assertTrue(shownText().contains("Transcribing… 35% (~4 min)"));
        assertEquals(UtubotPanelModel.Action.NONE, mModel.getState().action());
        assertTrue(mModel.getState().isWorking());
    }

    @Test
    public void aDelayedAnswerShowsTheServersErrorAndTheCountdown() {
        mSource.answer = answer("pending", "delayed");
        mSource.answer.error = "YouTube is limiting transcript downloads; retrying in ~1 min";
        mSource.answer.retryAfterSec = 45;

        mModel.show(video("Title"));

        assertTrue(shownText().contains("YouTube is limiting transcript downloads; retrying in ~1 min\nRetrying in 45 s"));
    }
}
