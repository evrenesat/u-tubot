package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Application;
import android.content.Context;

import androidx.preference.Preference;

import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.tv.ui.dialogs.AppPreferenceManager;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

/**
 * The cut-ready question is the first row of its dialog: the row the owner reads, greyed out so that focus lands on the answers. The
 * row is built by the real preference manager, so the title and the enabled state are what the owner sees (issue 274).
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
// The app's Conscrypt has no native library here, and no TLS is used
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotCutQuestionRowTest {
    private static final String QUESTION = "Director's cut ready: The demo (3:12). Play it now?";

    @Test
    public void theQuestionRowShowsTheWholeQuestionAndIsNotAChoice() {
        Context context = RuntimeEnvironment.getApplication();
        OptionItem question = UiOptionItem.from(QUESTION);
        question.setEnabled(false);

        Preference row = new AppPreferenceManager(context).createButtonPreference(OptionCategory.singleButton(question));

        assertEquals(QUESTION, row.getTitle().toString());
        assertFalse(row.isEnabled());
    }
}
