package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utils.QrCodeEncoder;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;

import io.reactivex.android.schedulers.AndroidSchedulers;

/**
 * The "Describe on phone…" sheet over the playing video. On a tablet the description is typed right here and built, or the
 * cut sheet is opened in the browser (where the voice button and the presets live); on a TV the waiting request's short
 * address is shown as a QR code, the address in text under it. Nothing is paused: the video keeps playing behind the sheet.
 * Back takes it away; the volume keys stay with the system.
 */
public final class UtubotCutQrView extends FrameLayout {
    private static final int SCRIM = 0xD0000000;
    private static final int TEXT = 0xFFFFFFFF;
    private static final int TITLE_TEXT_SIZE_SP = 20;
    private static final int HINT_TEXT_SIZE_SP = 16;
    private static final int PADDING_PX = 48;

    private UtubotCutQrView(Context context) {
        super(context);
    }

    /**
     * Puts the sheet over the activity's content; the video is not touched. Not an activity context: the address is said instead.
     */
    public static void show(Context context, CutRequest request) {
        Activity activity = activityOf(context);

        if (activity == null) {
            MessageHelpers.showLongMessage(context, UtubotManager.instance(context).cutRequestUrl(request.id));
            return;
        }

        ViewGroup content = activity.findViewById(android.R.id.content);
        close(content);
        content.addView(new UtubotCutQrView(activity).build(request),
                new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private static void close(ViewGroup content) {
        for (int i = content.getChildCount() - 1; i >= 0; i--) {
            if (content.getChildAt(i) instanceof UtubotCutQrView) {
                content.removeViewAt(i);
            }
        }
    }

    private UtubotCutQrView build(CutRequest request) {
        setBackgroundColor(SCRIM);
        setClickable(true);
        setFocusable(true);
        setFocusableInTouchMode(true);
        setOnKeyListener((view, keyCode, event) -> {
            switch (keyCode) {
                case KeyEvent.KEYCODE_VOLUME_UP:
                case KeyEvent.KEYCODE_VOLUME_DOWN:
                case KeyEvent.KEYCODE_VOLUME_MUTE:
                    return false; // the volume keys stay with the system: on a TV without CEC volume this is the only way to change it
            }

            if (event.getAction() != KeyEvent.ACTION_DOWN) {
                return true; // the rest of every press is this sheet's too
            }

            if (keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_ESCAPE) {
                detach();
                return true;
            }

            return true; // nothing under the sheet moves while it is up
        });

        LinearLayout column = new LinearLayout(getContext());
        column.setOrientation(LinearLayout.VERTICAL);
        column.setGravity(Gravity.CENTER_HORIZONTAL);
        column.setPadding(PADDING_PX, PADDING_PX, PADDING_PX, PADDING_PX);
        addView(column, new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));

        if (Helpers.isTouchSupported(getContext())) {
            buildTouchSheet(column, request);
        } else {
            buildQrSheet(column, request);
        }

        // The sheet holds the focus, so its keys are its own; a key that arrives before the attach is asked for again
        post(this::requestFocus);

        return this;
    }

    private void buildTouchSheet(LinearLayout column, CutRequest request) {
        TextView title = new TextView(getContext());
        title.setText(getString(R.string.utubot_cut_describe_title));
        title.setTextColor(TEXT);
        title.setTextSize(TITLE_TEXT_SIZE_SP);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        column.addView(title, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        EditText description = new EditText(getContext());
        description.setHint(getString(R.string.utubot_cut_describe_hint_touch));
        description.setTextColor(TEXT);
        description.setTextColorHint(0xB0FFFFFF);
        description.setTextSize(HINT_TEXT_SIZE_SP);
        description.setMinHeight(48 * getResources().getDisplayMetrics().density);
        description.setPadding(PADDING_PX / 2, PADDING_PX / 2, PADDING_PX / 2, PADDING_PX / 2);
        description.setBackground(null);
        column.addView(description, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout buttons = new LinearLayout(getContext());
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setGravity(Gravity.CENTER_HORIZONTAL);
        column.addView(buttons, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button openSheet = makeButton(getString(R.string.utubot_cut_describe_open));
        openSheet.setOnClickListener(v -> openInBrowser(getContext(), UtubotManager.instance(getContext()).cutRequestUrl(request.id)));
        buttons.addView(openSheet, buttonLayoutParams());

        Button build = makeButton(getString(R.string.utubot_cut_describe_build));
        build.setOnClickListener(v -> buildCut(request, description));
        buttons.addView(build, buttonLayoutParams());
    }

    private void buildQrSheet(LinearLayout column, CutRequest request) {
        String url = UtubotManager.instance(getContext()).cutRequestUrl(request.id);

        TextView address = new TextView(getContext());
        address.setText(url);
        address.setTextColor(TEXT);
        address.setTextSize(TITLE_TEXT_SIZE_SP);
        address.setTypeface(Typeface.DEFAULT_BOLD);
        address.setGravity(Gravity.CENTER);
        column.addView(address, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        DisplayMetrics metrics = getResources().getDisplayMetrics();
        int sidePx = Math.min(metrics.widthPixels, metrics.heightPixels) * 3 / 5;
        int codePx = QrCodeEncoder.toBitmap(url, sidePx) != null ? sidePx : 0;

        if (codePx > 0) {
            Bitmap code = QrCodeEncoder.toBitmap(url, codePx);
            ImageView codeView = new ImageView(getContext());
            codeView.setImageBitmap(code);
            codeView.setBackgroundColor(Color.WHITE);
            int padding = codePx / 16;
            codeView.setPadding(padding, padding, padding, padding);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(codePx + padding * 2, codePx + padding * 2);
            params.topMargin = padding;
            params.bottomMargin = padding;
            column.addView(codeView, params);
        }

        TextView hintView = new TextView(getContext());
        hintView.setText(getString(R.string.utubot_cut_describe_hint));
        hintView.setTextColor(TEXT);
        hintView.setTextSize(HINT_TEXT_SIZE_SP);
        hintView.setGravity(Gravity.CENTER);
        column.addView(hintView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private View makeButton(String label) {
        Button button = new Button(getContext());
        button.setText(label);
        button.setTextColor(TEXT);
        button.setPadding(32, 16, 32, 16);
        return button;
    }

    private LinearLayout.LayoutParams buttonLayoutParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.rightMargin = 16;
        return params;
    }

    private void buildCut(CutRequest request, EditText description) {
        String prompt = description.getText().toString().trim();

        if (prompt.isEmpty()) {
            MessageHelpers.showLongMessage(getContext(), getString(R.string.utubot_cut_describe_empty));
            return;
        }

        UtubotManager.instance(getContext())
                .fillCutRequestObserve(request.id, prompt, request.mode)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(
                        built -> {
                            UtubotManager.instance(getContext()).cutRequested(request.videoId, request.id, built.state);
                            if (UtubotCutWatcher.isPending(built.state)) {
                                UtubotCutNotices.instance(getContext()).ordered(request.id, request.videoId, request.title);
                            }
                            MessageHelpers.showLongMessage(getContext(), getString(R.string.utubot_cut_state_building));
                            detach();
                        },
                        error -> MessageHelpers.showLongMessage(getContext(),
                                getString(R.string.utubot_cut_describe_failed, describeError(error))));
    }

    private static void openInBrowser(Context context, String url) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        intent.addFlags(Intent.FLAG_GRANT_URI_PERMISSION);
        try {
            context.startActivity(intent);
        } catch (ActivityNotFoundException e) {
            Utils.showMultiChooser(context, Uri.parse(url));
        }
    }

    private String describeError(Throwable error) {
        return error.getMessage() != null ? error.getMessage() : getString(R.string.utubot_answer_none);
    }

    private void detach() {
        if (getParent() instanceof ViewGroup) {
            ((ViewGroup) getParent()).removeView(this);
        }
    }

    @Nullable
    private static Activity activityOf(Context context) {
        Context current = context;

        while (current instanceof ContextWrapper && !(current instanceof Activity)) {
            current = ((ContextWrapper) current).getBaseContext();
        }

        return current instanceof Activity ? (Activity) current : null;
    }
}
