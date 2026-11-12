package com.liskovsoft.smartyoutubetv2.common.utils;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.text.Editable;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.LayoutInflater;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import androidx.appcompat.app.AlertDialog;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import com.liskovsoft.sharedutils.helpers.KeyHelpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;

public class SimpleEditDialog {
    /**
     * No microphone key on the keyboard: "nm" for the AOSP keyboards, the other for Gboard (Android TV's included)
     */
    private static final String NO_MICROPHONE = "nm,com.google.android.inputmethod.latin.noMicrophoneKey";

    public interface OnChange {
        boolean onChange(String newValue);
    }

    public static void show(Context context, String dialogTitle, String defaultValue, OnChange onChange) {
        show(context, dialogTitle, dialogTitle, defaultValue, onChange, null);
    }

    public static void show(Context context, String dialogTitle, String dialogHint, String defaultValue, OnChange onChange) {
        show(context, dialogTitle, dialogHint, defaultValue, onChange, null);
    }

    public static void show(Context context, String dialogTitle, String dialogHint, String defaultValue, OnChange onChange, Runnable onDismiss) {
        show(context, dialogTitle, dialogHint, defaultValue, onChange, onDismiss, InputType.TYPE_NULL);
    }

    public static void showPassword(Context context, String dialogTitle, String defaultValue, OnChange onChange) {
        showPassword(context, dialogTitle, defaultValue, onChange, null);
    }

    public static void showPassword(Context context, String dialogTitle, String defaultValue, OnChange onChange, Runnable onDismiss) {
        show(context, dialogTitle, dialogTitle, defaultValue, onChange, onDismiss, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
    }

    /**
     * Digits only, e.g. a pairing code
     */
    public static void showNumber(Context context, String dialogTitle, String dialogHint, OnChange onChange, Runnable onDismiss) {
        show(context, dialogTitle, dialogHint, "", onChange, onDismiss, InputType.TYPE_CLASS_NUMBER);
    }

    /**
     * A name, e.g. of a subscription group: the keyboard starts with a capital letter
     */
    public static void showName(Context context, String dialogTitle, String defaultValue, OnChange onChange) {
        show(context, dialogTitle, dialogTitle, defaultValue, onChange, null, InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
    }

    /**
     * An address, e.g. of a server: no autocorrection, no suggestions, no capital letter, no voice input. The layout's type
     * (textUri|textPersonName) adds up to a postal address, which keyboards autocorrect.
     */
    public static void showUrl(Context context, String dialogTitle, String dialogHint, String defaultValue, OnChange onChange) {
        show(context, dialogTitle, dialogHint, defaultValue, onChange, null,
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS, NO_MICROPHONE);
    }

    private static void show(Context context, String dialogTitle, String dialogHint, String defaultValue, OnChange onChange, Runnable onDismiss, int inputType) {
        show(context, dialogTitle, dialogHint, defaultValue, onChange, onDismiss, inputType, null);
    }

    /**
     * @param inputType the InputType.TYPE_* of the field, or {@link InputType#TYPE_NULL} for the one of the layout
     * @param privateImeOptions for the keyboard (see EditorInfo.privateImeOptions), null for none
     */
    private static void show(Context context, String dialogTitle, String dialogHint, String defaultValue, OnChange onChange, Runnable onDismiss,
                             int inputType, String privateImeOptions) {
        AlertDialog.Builder builder = new AlertDialog.Builder(context, R.style.AppDialog);
        LayoutInflater inflater = LayoutInflater.from(context);
        View contentView = inflater.inflate(R.layout.simple_edit_dialog, null);

        EditText editField = contentView.findViewById(R.id.simple_edit_value);
        if (inputType != InputType.TYPE_NULL) {
            editField.setInputType(inputType);
        }
        if (privateImeOptions != null) {
            editField.setPrivateImeOptions(privateImeOptions);
        }
        KeyHelpers.fixShowKeyboard(editField);

        editField.setText(defaultValue);
        editField.setHint(dialogHint);
        editField.setNextFocusDownId(android.R.id.button1); // OK button
        // A URI field makes most keyboards show "Go": say which action the key sends, and handle every one of them below
        editField.setImeOptions(EditorInfo.IME_ACTION_DONE);

        if (defaultValue != null) { // move cursor to the end
            editField.setSelection(defaultValue.length());
        }

        // keep empty, will override below.
        // https://stackoverflow.com/a/15619098/5379584
        AlertDialog configDialog = builder
                .setTitle(dialogTitle)
                .setView(contentView)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> { })
                .setNegativeButton(android.R.string.cancel, (dialog, which) -> { })
                // The remote has no way to paste into the field
                .setNeutralButton(android.R.string.paste, (dialog, which) -> { })
                .create();

        if (onDismiss != null) {
            configDialog.setOnDismissListener(dialog -> onDismiss.run());
        }

        // Enter presses OK, whether the keyboard sends an action or the Enter key itself (e.g. a hardware keyboard)
        editField.setOnEditorActionListener((v, actionId, event) -> {
            boolean isEnterKey = event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER;

            if (!isSubmitAction(actionId) && !isEnterKey) {
                return false;
            }

            // Once per press: the key comes down and up, and a keyboard might send the action and the key both
            if ((event == null || event.getAction() == KeyEvent.ACTION_DOWN) && configDialog.isShowing()) {
                configDialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick();
            }

            return true;
        });

        // Back hides the keyboard only: some keyboards pass it on to the dialog, which would be lost with the typed text
        configDialog.setOnKeyListener((dialog, keyCode, event) ->
                keyCode == KeyEvent.KEYCODE_BACK && consumeBack(event, isKeyboardShown(editField), () -> hideKeyboard(editField)));

        try {
            configDialog.show();
        } catch (RuntimeException e) {
            // BadTokenException: Unable to add window -- token null is not for an application
            // RuntimeException: InputChannel is not initialized
            e.printStackTrace();
            MessageHelpers.showMessage(context, e.getMessage());
            return;
        }

        configDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener((view) -> {
            String newValue = editField.getText().toString();

            if (newValue.trim().isEmpty()) {
                // Empty fields not allowed
                editField.setHint(R.string.enter_value);
                MessageHelpers.showMessage(context, R.string.enter_value);
                return;
            }

            boolean dismiss = onChange.onChange(newValue);

            if (dismiss) {
                configDialog.dismiss();
            }
        });

        configDialog.getButton(AlertDialog.BUTTON_NEGATIVE).setOnClickListener((view) -> configDialog.dismiss());

        // Stays open: the pasted text can be checked before OK
        configDialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener((view) -> paste(context, editField));

        //editField.setNextFocusDownId(configDialog.getButton(AlertDialog.BUTTON_POSITIVE).getId()); // OK button
    }

    /**
     * Back while the keyboard is up hides it and nothing more (the dialog stays, with its text).
     *
     * @return true if the key is consumed
     */
    static boolean consumeBack(KeyEvent event, boolean keyboardShown, Runnable hideKeyboard) {
        if (!keyboardShown) {
            return false;
        }

        if (event.getAction() == KeyEvent.ACTION_UP) {
            hideKeyboard.run();
        }

        return true;
    }

    static boolean isSubmitAction(int actionId) {
        return actionId == EditorInfo.IME_ACTION_DONE || actionId == EditorInfo.IME_ACTION_NEXT || actionId == EditorInfo.IME_ACTION_GO
                || actionId == EditorInfo.IME_ACTION_SEND || actionId == EditorInfo.IME_ACTION_SEARCH;
    }

    private static boolean isKeyboardShown(View view) {
        WindowInsetsCompat insets = ViewCompat.getRootWindowInsets(view);

        return insets != null && insets.isVisible(WindowInsetsCompat.Type.ime());
    }

    private static void hideKeyboard(View view) {
        InputMethodManager imm = (InputMethodManager) view.getContext().getSystemService(Context.INPUT_METHOD_SERVICE);

        if (imm != null) {
            imm.hideSoftInputFromWindow(view.getWindowToken(), 0);
        }
    }

    /**
     * Puts the clipboard's text in place of the selection, or at the cursor. One line: the fields are single-line.
     */
    private static void paste(Context context, EditText editField) {
        ClipboardManager clipboard = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
        ClipData clip = clipboard != null ? clipboard.getPrimaryClip() : null;
        CharSequence text = clip != null && clip.getItemCount() > 0 ? clip.getItemAt(0).coerceToText(context) : null;
        String pasted = text != null ? text.toString().replaceAll("\\s*[\\r\\n]+\\s*", " ").trim() : "";

        if (pasted.isEmpty()) {
            MessageHelpers.showMessage(context, R.string.clipboard_empty);
            return;
        }

        Editable editable = editField.getText();
        // -1 when the field never had the cursor
        int start = Math.max(0, Math.min(editField.getSelectionStart(), editField.getSelectionEnd()));
        int end = Math.max(0, Math.max(editField.getSelectionStart(), editField.getSelectionEnd()));

        editable.replace(start, end, pasted);
        editField.setSelection(start + pasted.length());
        editField.requestFocus();
    }
}
