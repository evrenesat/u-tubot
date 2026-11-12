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

    @Test
    public void thePanelPointsToTheInfoKeyForAVideoThatCanBeTranscribed() {
        State state = state(Phase.NEEDS_TRANSCRIPT, "No captions. Transcribe the audio in the background?", true, 4, UtubotModels.UNKNOWN);

        assertEquals("No captions — press Info to transcribe", UtubotStateText.noCaptionsShort(mActivity, state));
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
        assertEquals("Transcribing… 0%", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 4, 0)));
        assertEquals("Transcribing… 42%", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 4, 42)));
        assertEquals("Transcribing…", UtubotStateText.transcribing(mActivity, state(Phase.TRANSCRIBING, null, false, 4, UtubotModels.UNKNOWN)));
    }

    @Test
    public void theActionNamesTheEstimateInMinutes() {
        assertEquals("Transcribe in background (~4 min)", UtubotStateText.transcribeAction(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, true, 4, UtubotModels.UNKNOWN)));
        assertEquals("Transcribe in background", UtubotStateText.transcribeAction(mActivity, state(Phase.NEEDS_TRANSCRIPT, null, true, 0, UtubotModels.UNKNOWN)));
    }
}
