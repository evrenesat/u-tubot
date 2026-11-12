package com.liskovsoft.smartyoutubetv2.common.utils;

import android.app.Activity;
import android.view.KeyEvent;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;

import androidx.appcompat.app.AlertDialog;

import com.liskovsoft.smartyoutubetv2.common.R;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowDialog;
import org.robolectric.shadows.ShadowToast;

import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class SimpleEditDialogTest {
    private Activity mActivity;
    private final List<String> mSubmitted = new ArrayList<>();

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mActivity.setTheme(R.style.AppDialog);
    }

    private AlertDialog showUrlDialog() {
        SimpleEditDialog.showUrl(mActivity, "Title", "hint", "", value -> {
            mSubmitted.add(value);
            return true;
        });

        AlertDialog dialog = (AlertDialog) ShadowDialog.getLatestDialog();
        assertNotNull(dialog);
        return dialog;
    }

    private static EditText field(AlertDialog dialog) {
        return dialog.findViewById(R.id.simple_edit_value);
    }

    @Test
    public void okButton_submitsTheText() {
        AlertDialog dialog = showUrlDialog();
        field(dialog).setText("utubot.example.com");

        dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick();

        assertEquals(1, mSubmitted.size());
        assertEquals("utubot.example.com", mSubmitted.get(0));
        assertFalse(dialog.isShowing());
    }

    @Test
    public void keyboardActions_submitLikeOk() {
        int[] actions = {EditorInfo.IME_ACTION_DONE, EditorInfo.IME_ACTION_GO, EditorInfo.IME_ACTION_NEXT, EditorInfo.IME_ACTION_SEND,
                EditorInfo.IME_ACTION_SEARCH};

        for (int action : actions) {
            mSubmitted.clear();
            AlertDialog dialog = showUrlDialog();
            field(dialog).setText("nas:8790");

            field(dialog).onEditorAction(action);

            assertEquals("action " + action, 1, mSubmitted.size());
            assertEquals("nas:8790", mSubmitted.get(0));
        }
    }

    @Test
    public void unrelatedKeyboardAction_isIgnored() {
        AlertDialog dialog = showUrlDialog();
        field(dialog).setText("nas:8790");

        field(dialog).onEditorAction(EditorInfo.IME_ACTION_NONE);

        assertTrue(mSubmitted.isEmpty());
        assertTrue(dialog.isShowing());
    }

    @Test
    public void emptyInput_isNoOpWithMessage() {
        AlertDialog dialog = showUrlDialog();
        field(dialog).setText("   ");

        dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick();

        assertTrue(mSubmitted.isEmpty());
        assertTrue(dialog.isShowing());
        assertEquals(mActivity.getString(R.string.enter_value), ShadowToast.getTextOfLatestToast());
    }

    @Test
    public void keyboardOpenBackIsConsumed_thenOkStillSubmits() {
        AlertDialog dialog = showUrlDialog();
        field(dialog).setText("utubot.example.com");
        int[] hidden = {0};

        // The keyboard is up: Back (down and up) only hides it
        assertTrue(SimpleEditDialog.consumeBack(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BACK), true, () -> hidden[0]++));
        assertTrue(SimpleEditDialog.consumeBack(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BACK), true, () -> hidden[0]++));
        assertEquals(1, hidden[0]);
        assertTrue(dialog.isShowing());
        assertEquals("utubot.example.com", field(dialog).getText().toString());

        dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick();

        assertEquals(1, mSubmitted.size());
        assertEquals("utubot.example.com", mSubmitted.get(0));
    }

    @Test
    public void keyboardHiddenBack_goesToTheDialog() {
        assertFalse(SimpleEditDialog.consumeBack(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BACK), false, () -> { }));
    }
}
