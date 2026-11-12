package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.Phase;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel.State;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.Collections;

import static org.junit.Assert.assertEquals;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotStateTextTest {
    private Activity mActivity;

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
    }

    private static State state(Phase phase, @Nullable String message, boolean canTranscribe, int estimateMinutes, int progressPercent) {
        return new State(new Video(), phase, Collections.emptyList(), null, null, null, null, null, message, canTranscribe, estimateMinutes, progressPercent);
    }

    private static State delayedState(@Nullable String message, int retryInSec) {
        return new State(new Video(), Phase.DELAYED, Collections.emptyList(), null, null, null, null, null, message, false, 0, UtubotModels.UNKNOWN, null,
                retryInSec);
    }

    @Test
    public void thePanelShowsTheServersMessageForAVideoThatCanBeTranscribed() {
        State state = state(Phase.NEEDS_TRANSCRIPT, "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~90 s)?", true, 2,
                UtubotModels.UNKNOWN);

        assertEquals("Captions are temporarily unavailable from YouTube; transcribe the audio instead (~90 s)?",
                UtubotStateText.noCaptionsShort(mActivity, state));
    }

    @Test
    public void thePanelPointsToTheInfoKeyWhenTheServerSaidNothing() {
        assertEquals("No captions — press Info to transcribe",
                UtubotStateText.noCaptionsShort(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, true, 4, UtubotModels.UNKNOWN)));
        assertEquals("No captions — press Info to transcribe",
                UtubotStateText.noCaptionsShort(mActivity, state(Phase.NEEDS_TRANSCRIPT, "  ", true, 4, UtubotModels.UNKNOWN)));
    }

    @Test
    public void thePanelGivesTheReasonForAVideoThatCannotBeTranscribed() {
        assertEquals("Live streams have no transcript", UtubotStateText.noCaptionsShort(mActivity,
                state(Phase.NEEDS_TRANSCRIPT, "Live streams have no transcript", false, 0, UtubotModels.UNKNOWN)));
        assertEquals("No captions are available for this video", UtubotStateText.noCaptionsShort(mActivity,
                state(Phase.NEEDS_TRANSCRIPT, null, false, 0, UtubotModels.UNKNOWN)));
    }

    @Test
    public void theViewShowsTheBackendsMessageElseItsOwn() {
        assertEquals("Server words", UtubotStateText.noCaptionsLong(mActivity, state(Phase.NEEDS_TRANSCRIPT, "Server words", true, 0, UtubotModels.UNKNOWN)));
        assertEquals("This video has no captions. Its audio can be transcribed in the background.",
                UtubotStateText.noCaptionsLong(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, true, 0, UtubotModels.UNKNOWN)));
        assertEquals("No captions are available for this video",
                UtubotStateText.noCaptionsLong(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, false, 0, UtubotModels.UNKNOWN)));
    }

    @Test
    public void aDelayShowsTheBackendsReasonElseTheAppsWords() {
        assertEquals("YouTube asked us to wait", UtubotStateText.delayed(mActivity, state(Phase.DELAYED, "YouTube asked us to wait", false, 0, UtubotModels.UNKNOWN)));
        assertEquals("YouTube is slowing us down, trying again shortly",
                UtubotStateText.delayed(mActivity, state(Phase.DELAYED, null, false, 0, UtubotModels.UNKNOWN)));
    }

    @Test
    public void transcribingShowsThePercentageWhenItIsKnown() {
        assertEquals("Transcribing… 0%", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 0, 0)));
        assertEquals("Transcribing… 42%", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 0, 42)));
        assertEquals("Transcribing…", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 0, UtubotModels.UNKNOWN)));
    }

    @Test
    public void transcribingShowsTheEstimateNextToTheProgress() {
        assertEquals("Transcribing… 42% (~4 min)", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 4, 42)));
        assertEquals("Transcribing… (~4 min)", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 4, UtubotModels.UNKNOWN)));
        assertEquals("Transcribing… 42%", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 0, 42)));
    }

    @Test
    public void aDelayCountsDownInSecondsThenMinutes() {
        assertEquals("Retrying in 42 s", UtubotStateText.retryIn(mActivity, delayedState("x", 42)));
        assertEquals("Retrying in 59 s", UtubotStateText.retryIn(mActivity, delayedState("x", 59)));
        assertEquals("Retrying in 1:00", UtubotStateText.retryIn(mActivity, delayedState("x", 60)));
        assertEquals("Retrying in 2:05", UtubotStateText.retryIn(mActivity, delayedState("x", 125)));
        assertEquals("", UtubotStateText.retryIn(mActivity, delayedState("x", UtubotModels.UNKNOWN)));
    }

    @Test
    public void theDelayedTextIsTheServersErrorThenTheCountdown() {
        assertEquals("YouTube is limiting transcript downloads; retrying in ~1 min\nRetrying in 30 s",
                UtubotStateText.delayedWithCountdown(mActivity, delayedState("YouTube is limiting transcript downloads; retrying in ~1 min", 30)));
        assertEquals("YouTube is slowing us down, trying again shortly\nRetrying in 30 s",
                UtubotStateText.delayedWithCountdown(mActivity, delayedState(null, 30)));
        assertEquals("Server words", UtubotStateText.delayedWithCountdown(mActivity, delayedState("Server words", UtubotModels.UNKNOWN)));
    }

    @Test
    public void theActionNamesTheEstimateInMinutes() {
        assertEquals("Transcribe in background (~4 min)", UtubotStateText.transcribeAction(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, true, 4, UtubotModels.UNKNOWN)));
        assertEquals("Transcribe in background", UtubotStateText.transcribeAction(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, true, 0, UtubotModels.UNKNOWN)));
    }
}
