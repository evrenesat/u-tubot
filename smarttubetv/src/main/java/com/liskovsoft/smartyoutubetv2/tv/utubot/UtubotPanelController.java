package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewParent;
import android.view.ViewTreeObserver;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.tv.R;

import java.lang.ref.WeakReference;

/**
 * Opens the Summary panel over an activity (browse, search, channel) for the card that keeps the focus long enough.
 * Hooked into LeanbackActivity: resume attaches it, pause hides it (e.g. when the player opens), destroy removes it.
 * D-pad: Right on the edge of the grid moves the focus into the panel; Back or Left returns it to the grid.
 */
public class UtubotPanelController {
    private final Activity mActivity;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final UtubotSettings mSettings;
    private final long mDebounceMs;
    private final long mEdgeCheckMs;
    private UtubotPanelView mPanel;
    private UtubotPanelModel mModel;
    private ViewTreeObserver.OnGlobalFocusChangeListener mFocusListener;
    private WeakReference<View> mGridFocus = new WeakReference<>(null);
    private Video mPendingVideo;
    private final Runnable mShowPending = this::showPending;
    private final Runnable mOnModeChanged = () -> mHandler.post(this::applyMode);

    public UtubotPanelController(Activity activity) {
        mActivity = activity;
        mSettings = UtubotSettings.instance(activity);
        mDebounceMs = activity.getResources().getInteger(R.integer.utubot_panel_focus_debounce_ms);
        mEdgeCheckMs = activity.getResources().getInteger(R.integer.utubot_panel_edge_check_ms);
    }

    public void onResume() {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        ensurePanel();
        mFocusListener = (oldFocus, newFocus) -> onFocusChanged(newFocus);
        mActivity.getWindow().getDecorView().getViewTreeObserver().addOnGlobalFocusChangeListener(mFocusListener);
        mSettings.addPanelListener(mOnModeChanged);
    }

    public void onPause() {
        mHandler.removeCallbacksAndMessages(null);
        mSettings.removePanelListener(mOnModeChanged);

        if (mFocusListener != null) {
            mActivity.getWindow().getDecorView().getViewTreeObserver().removeOnGlobalFocusChangeListener(mFocusListener);
            mFocusListener = null;
        }

        hide();
    }

    public void onDestroy() {
        onPause();

        if (mPanel != null && mPanel.getParent() instanceof ViewGroup) {
            ((ViewGroup) mPanel.getParent()).removeView(mPanel);
        }

        mPanel = null;
        mModel = null;
    }

    /**
     * @return the key was used here
     */
    public boolean dispatchKeyEvent(KeyEvent event) {
        if (mPanel == null || mPanel.getVisibility() != View.VISIBLE || event.getAction() != KeyEvent.ACTION_DOWN) {
            return false;
        }

        int key = event.getKeyCode();

        if (mPanel.hasPanelFocus()) {
            boolean isReturn = key == KeyEvent.KEYCODE_BACK || key == KeyEvent.KEYCODE_DPAD_LEFT;
            return isReturn && returnToGrid();
        }

        if (key == KeyEvent.KEYCODE_DPAD_RIGHT && event.getRepeatCount() == 0) {
            View focused = mActivity.getCurrentFocus();
            mHandler.postDelayed(() -> moveIntoPanelIfStuck(focused), mEdgeCheckMs);
        }

        return false;
    }

    private void moveIntoPanelIfStuck(@Nullable View focusBefore) {
        if (focusBefore != null && mActivity.getCurrentFocus() == focusBefore && mPanel != null) {
            mGridFocus = new WeakReference<>(focusBefore);
            mPanel.focusPrompt();
        }
    }

    private boolean returnToGrid() {
        View grid = mGridFocus.get();

        if (grid != null && grid.isAttachedToWindow() && grid.requestFocus()) {
            return true;
        }

        return false;
    }

    private void ensurePanel() {
        if (mPanel != null) {
            return;
        }

        ViewGroup content = mActivity.findViewById(android.R.id.content);
        mPanel = new UtubotPanelView(mActivity);
        mModel = new UtubotPanelModel(UtubotManager.instance(mActivity), state -> {
            if (mPanel != null) {
                mPanel.bind(state);
            }
        });
        mPanel.setOnPromptPicked(key -> mModel.selectPrompt(key));
        content.addView(mPanel, UtubotPanelView.layoutParams(mActivity, content.getWidth() > 0 ? content.getWidth() : mActivity.getResources().getDisplayMetrics().widthPixels));
    }

    private void onFocusChanged(@Nullable View newFocus) {
        if (!mSettings.isSummaryPanelEnabled()) {
            return;
        }

        if (newFocus == null || isInPanel(newFocus)) {
            return;
        }

        Video video = findVideo(newFocus);

        if (video == null || video.videoId == null) {
            return;
        }

        mPendingVideo = video;
        mHandler.removeCallbacks(mShowPending);
        mHandler.postDelayed(mShowPending, mDebounceMs);
    }

    private void showPending() {
        Video video = mPendingVideo;
        mPendingVideo = null;

        if (video == null || mPanel == null || !mSettings.isSummaryPanelEnabled()) {
            return;
        }

        Video shown = mModel.getVideo();

        if (shown != null && video.videoId.equals(shown.videoId) && mPanel.getVisibility() == View.VISIBLE) {
            return;
        }

        mPanel.setVisibility(View.VISIBLE);
        mModel.show(video);
    }

    private void applyMode() {
        if (!mSettings.isSummaryPanelEnabled()) {
            hide();
        } else if (mFocusListener != null) {
            onFocusChanged(mActivity.getCurrentFocus());
        }
    }

    private void hide() {
        mHandler.removeCallbacks(mShowPending);
        mPendingVideo = null;

        if (mModel != null) {
            mModel.dispose();
        }

        if (mPanel != null) {
            mPanel.setVisibility(View.GONE);
        }
    }

    private boolean isInPanel(View view) {
        for (ViewParent parent = view.getParent(); parent != null; parent = parent.getParent()) {
            if (parent == mPanel) {
                return true;
            }
        }

        return view == mPanel;
    }

    /**
     * The video of the card the view belongs to (see VideoCardPresenter and ModernVideoCard)
     */
    @Nullable
    static Video findVideo(View view) {
        View current = view;

        while (current != null) {
            Object tag = current.getTag(R.id.utubot_card_video);

            if (tag instanceof Video) {
                return (Video) tag;
            }

            ViewParent parent = current.getParent();
            current = parent instanceof View ? (View) parent : null;
        }

        return null;
    }
}
