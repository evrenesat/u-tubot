package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewParent;
import android.view.ViewTreeObserver;
import android.widget.FrameLayout;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.misc.MotherActivity;
import com.liskovsoft.smartyoutubetv2.common.utubot.PanelCoordinator;
import com.liskovsoft.smartyoutubetv2.common.utubot.FocusDebouncer;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotAnswerModel;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotKeys;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotMenu;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotOpenRequests;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPanelModel;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotScheduler;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotUiHost;
import com.liskovsoft.smartyoutubetv2.tv.R;

import java.lang.ref.WeakReference;

/**
 * The u-tubot overlays of an activity (browse, search, channel). Hooked into LeanbackActivity: resume attaches it, pause hides
 * everything (e.g. when the player opens), destroy removes it.
 * <ul>
 * <li>The passive Summary panel: a preview of the card that keeps the focus for the pause of the settings. It never takes the focus
 * and never handles a key. It is up only while a card has the focus (see {@link PanelCoordinator}).</li>
 * <li>The Summary view (and the AI answer): a focused card over the screen. Opened with the Info key on a card or from the video
 * menu; Back closes it and the focus returns to the same card.</li>
 * </ul>
 */
public class UtubotPanelController implements UtubotUiHost.Host {
    private final Activity mActivity;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final UtubotSettings mSettings;
    private final UtubotManager mManager;
    private final UtubotScheduler mScheduler = UtubotScheduler.mainThread();
    private final PanelCoordinator mCoordinator;
    private final FocusDebouncer mPromptDebouncer;
    private UtubotPanelView mPanel;
    private UtubotPanelModel mPanelModel;
    private UtubotSummaryOverlay mOverlay;
    private UtubotPanelModel mViewModel;
    private UtubotAnswerModel mAnswerModel;
    private ViewTreeObserver.OnGlobalFocusChangeListener mFocusListener;
    private WeakReference<View> mReturnFocus = new WeakReference<>(null);
    private WeakReference<View> mWatchedCard = new WeakReference<>(null);
    private Video mFocusedVideo;
    private int mSwallowedKey = KeyEvent.KEYCODE_UNKNOWN;
    private boolean mIsCreated;
    private final View.OnAttachStateChangeListener mCardWatcher = new View.OnAttachStateChangeListener() {
        @Override
        public void onViewAttachedToWindow(View view) {
        }

        @Override
        public void onViewDetachedFromWindow(View view) {
            Video video = findVideo(view);
            mCoordinator.onCardGone(video != null ? video.videoId : null);
        }
    };
    private final Runnable mOnModeChanged = () -> mHandler.post(this::applyMode);

    public UtubotPanelController(Activity activity) {
        mActivity = activity;
        mSettings = UtubotSettings.instance(activity);
        mManager = UtubotManager.instance(activity);
        mCoordinator = new PanelCoordinator(mScheduler, () -> mSettings.getPanelDelayMs(), new PanelCoordinator.Output() {
            @Override
            public void showWaiting(String key) {
                if (mPanel != null && mFocusedVideo != null) {
                    placePanel();
                    mPanel.setVisibility(View.VISIBLE);
                    mPanelModel.waitFor(mFocusedVideo);
                }
            }

            @Override
            public void showSettled(String key) {
                if (mPanelModel != null && mFocusedVideo != null) {
                    mPanelModel.show(mFocusedVideo);
                }
            }

            @Override
            public void hide() {
                hidePanel();
            }
        });
        mPromptDebouncer = new FocusDebouncer(mScheduler, () -> UtubotSettings.VIEW_PROMPT_DELAY_MS, new FocusDebouncer.Listener() {
            @Override
            public void onPending(String key) {
            }

            @Override
            public void onSettled(String key) {
                if (mViewModel != null) {
                    mViewModel.preview(key);
                }
            }
        });
    }

    public void onResume() {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        if (!mIsCreated) {
            mIsCreated = true;
            UtubotUiHost.onHostCreated();
        }

        ensureViews();
        mCoordinator.onResume();
        mFocusListener = (oldFocus, newFocus) -> onFocusChanged(newFocus);
        mActivity.getWindow().getDecorView().getViewTreeObserver().addOnGlobalFocusChangeListener(mFocusListener);
        mSettings.addPanelListener(mOnModeChanged);
        UtubotUiHost.setResumedHost(this);

        // The menu dialog above this screen closed with a request, or the focus is on a card already
        mHandler.post(this::resumeContent);
    }

    public void onPause() {
        UtubotUiHost.clearResumedHost(this);
        mHandler.removeCallbacksAndMessages(null);
        mSettings.removePanelListener(mOnModeChanged);

        if (mFocusListener != null) {
            mActivity.getWindow().getDecorView().getViewTreeObserver().removeOnGlobalFocusChangeListener(mFocusListener);
            mFocusListener = null;
        }

        mSwallowedKey = KeyEvent.KEYCODE_UNKNOWN;
        mCoordinator.onPause();
        unwatchCard();
        mPromptDebouncer.cancel();
        closeOverlay(false);
        hidePanel();
    }

    public void onDestroy() {
        onPause();

        if (mIsCreated) {
            mIsCreated = false;
            UtubotUiHost.onHostDestroyed();
        }

        removeFromParent(mPanel);
        removeFromParent(mOverlay);
        mPanel = null;
        mOverlay = null;
        mPanelModel = null;
        mViewModel = null;
        mAnswerModel = null;
    }

    @Override
    public void onOpenRequest() {
        mHandler.post(() -> openRequested());
    }

    /**
     * @return the key was used here
     */
    public boolean dispatchKeyEvent(KeyEvent event) {
        boolean isUsed = handleKey(event);

        // A key used here never reaches the activity, which is what ends the screensaver's dimming
        if (isUsed && event.getAction() == KeyEvent.ACTION_DOWN && mActivity instanceof MotherActivity) {
            ((MotherActivity) mActivity).getScreensaverManager().enable();
        }

        return isUsed;
    }

    private boolean handleKey(KeyEvent event) {
        if (mPanel == null) {
            return false;
        }

        int key = event.getKeyCode();

        // The rest of a press whose start was used here (its repeats and its release) isn't the app's either
        if (key == mSwallowedKey) {
            boolean isNewPress = event.getAction() == KeyEvent.ACTION_DOWN && event.getRepeatCount() == 0;

            // A press that starts again means the release of the last one got lost
            if (event.getAction() == KeyEvent.ACTION_UP || isNewPress) {
                mSwallowedKey = KeyEvent.KEYCODE_UNKNOWN;
            }

            if (!isNewPress) {
                return true;
            }
        }

        boolean isViewOpen = mOverlay != null && mOverlay.isOpen();

        // The focus never rests on the screen under the view: the first key takes it back instead of moving the grid
        if (isViewOpen && UtubotKeys.isDirectionKey(key) && !mOverlay.hasFocus()) {
            mOverlay.restoreFocus();
            return true;
        }

        Video focused = isViewOpen ? null : findVideoOfFocus();
        UtubotKeys.Result result = UtubotKeys.resolve(key, event.getAction(), event.getRepeatCount(), isViewOpen, mSettings.isSummaryPanelEnabled(),
                focused != null && focused.videoId != null, mCoordinator.isVisible());

        switch (result) {
            case TOUCH:
                mCoordinator.onKeyActivity();
                return false;
            case OPEN_SUMMARY:
                mSwallowedKey = key;
                openSummary(focused);
                return true;
            case CLOSE_VIEW:
                mSwallowedKey = key;
                closeOverlay(true);
                return true;
            case HIDE_PANEL:
                // The focus stays on the card; the next Back is the app's (the side menu, or leaving)
                mSwallowedKey = key;
                mCoordinator.dismiss();
                return true;
            case CONSUME:
                return true;
            default:
                return false;
        }
    }

    private void ensureViews() {
        if (mPanel != null) {
            return;
        }

        ViewGroup content = mActivity.findViewById(android.R.id.content);

        mPanel = new UtubotPanelView(mActivity);
        mPanelModel = new UtubotPanelModel(mManager, UtubotPanelModel.Mode.PANEL, state -> {
            if (mPanel != null) {
                mPanel.bind(state);
            }
        });
        content.addView(mPanel, UtubotPanelView.layoutParams(mActivity, contentWidth(content), 0));

        mOverlay = new UtubotSummaryOverlay(mActivity);
        mViewModel = new UtubotPanelModel(mManager, UtubotPanelModel.Mode.VIEW, state -> {
            if (mOverlay != null) {
                mOverlay.bind(state);
            }
        });
        mAnswerModel = new UtubotAnswerModel(mManager, insight -> UtubotMenu.formatInsight(mActivity, insight), state -> {
            if (mOverlay != null) {
                mOverlay.bind(state);
            }
        });
        mOverlay.setListener(new UtubotSummaryOverlay.Listener() {
            @Override
            public void onRetry() {
                if (mOverlay.isAnswer()) {
                    mAnswerModel.retry();
                } else {
                    mViewModel.retry();
                }
            }

            @Override
            public void onTranscribe() {
                if (!mOverlay.isAnswer()) {
                    mViewModel.transcribe();
                    return;
                }

                // The answer of a video without captions: the transcription is started from the Summary view of the same video
                Video video = mAnswerModel.getVideo();

                if (video != null) {
                    openSummary(video);
                    mViewModel.transcribe();
                }
            }

            @Override
            public void onHighlight(String key) {
                mPromptDebouncer.focus(key);
            }

            @Override
            public void onPick(String key) {
                mViewModel.pin(key);
                MessageHelpers.showMessage(mActivity, mActivity.getString(R.string.utubot_view_prompt_kept, labelOf(key)));
            }
        });
        content.addView(mOverlay, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    /**
     * The view that has the focus in the activity's window
     */
    @Nullable
    private View currentFocus() {
        return mActivity.getWindow().getDecorView().findFocus();
    }

    private int contentWidth(ViewGroup content) {
        return content.getWidth() > 0 ? content.getWidth() : mActivity.getResources().getDisplayMetrics().widthPixels;
    }

    /**
     * How far down the screen's own top bar reaches (the Modern skin's bar, the classic title), in the content's coordinates: the panel
     * stays below it. The bar isn't laid out when the panel is attached, so this is read each time the panel comes up.
     */
    private int topInset(ViewGroup content) {
        int bottom = 0;

        for (int id : new int[]{R.id.modern_browse_top_bar, androidx.leanback.R.id.browse_title_group}) {
            View bar = mActivity.findViewById(id);

            if (bar != null && bar.isShown() && bar.getHeight() > 0) {
                int[] barLocation = new int[2];
                int[] contentLocation = new int[2];
                bar.getLocationInWindow(barLocation);
                content.getLocationInWindow(contentLocation);
                bottom = Math.max(bottom, barLocation[1] + bar.getHeight() - contentLocation[1]);
            }
        }

        return bottom;
    }

    private void placePanel() {
        ViewGroup content = (ViewGroup) mPanel.getParent();

        if (content == null) {
            return;
        }

        FrameLayout.LayoutParams wanted = UtubotPanelView.layoutParams(mActivity, contentWidth(content), topInset(content));
        FrameLayout.LayoutParams current = (FrameLayout.LayoutParams) mPanel.getLayoutParams();

        if (current.width != wanted.width || current.topMargin != wanted.topMargin) {
            mPanel.setLayoutParams(wanted);
        }
    }

    private String labelOf(String key) {
        UtubotPanelModel.State state = mViewModel.getState();

        if (state != null) {
            for (Prompt prompt : state.prompts) {
                if (prompt.key.equals(key)) {
                    return prompt.label;
                }
            }
        }

        return key;
    }

    private void resumeContent() {
        if (!openRequested()) {
            applyMode();
        }
    }

    /**
     * @return a request of the menu was opened
     */
    private boolean openRequested() {
        UtubotOpenRequests.Request request = UtubotUiHost.take();

        if (request == null || mPanel == null) {
            return false;
        }

        if (request.kind == UtubotOpenRequests.Kind.SUMMARY) {
            openSummary(request.video);
        } else {
            openAnswer(request.video);
        }

        return true;
    }

    private void openSummary(Video video) {
        beginOverlay();
        mOverlay.open(false);
        mViewModel.show(video);
    }

    private void openAnswer(Video video) {
        beginOverlay();
        mOverlay.open(true);
        mAnswerModel.show(video);
    }

    private void beginOverlay() {
        View focus = currentFocus();

        if (focus != null && !isInOverlay(focus)) {
            mReturnFocus = new WeakReference<>(focus);
        }

        mCoordinator.setModalOpen(true);
        mPromptDebouncer.cancel();
        mViewModel.dispose();
        mAnswerModel.dispose();
    }

    /**
     * @param restoreFocus the focus goes back to the card it came from
     */
    private void closeOverlay(boolean restoreFocus) {
        if (mOverlay == null || !mOverlay.isOpen()) {
            return;
        }

        mPromptDebouncer.cancel();
        mViewModel.dispose();
        mAnswerModel.dispose();
        // Before the view goes: the focus it leaves is already a card of the list for the panel
        mCoordinator.setModalOpen(false);
        mOverlay.close();

        View card = mReturnFocus.get();
        mReturnFocus = new WeakReference<>(null);

        if (restoreFocus && card != null && card.isAttachedToWindow()) {
            card.requestFocus();
        }

        if (restoreFocus) {
            // Asking for the focus a card has already gives no focus change: the panel looks at where the focus is now
            onFocusChanged(currentFocus());
        }
    }

    private void applyMode() {
        mCoordinator.setEnabled(mSettings.isSummaryPanelEnabled());

        if (mSettings.isSummaryPanelEnabled() && mOverlay != null && !mOverlay.isOpen()) {
            onFocusChanged(currentFocus());
        }
    }

    private void onFocusChanged(@Nullable View newFocus) {
        if (mOverlay != null && mOverlay.isOpen()) {
            // The grid took the focus back (e.g. a list reload): the view keeps it
            if (newFocus == null || !isInOverlay(newFocus)) {
                mHandler.post(() -> {
                    if (mOverlay != null && mOverlay.isOpen() && !mOverlay.hasFocus()) {
                        mOverlay.restoreFocus();
                    }
                });
            }
            return;
        }

        unwatchCard();
        Video video = newFocus != null ? findVideo(newFocus) : null;

        if (video == null || video.videoId == null) {
            mFocusedVideo = null;
            mCoordinator.onNothingFocused();
            return;
        }

        mFocusedVideo = video;
        watchCard(newFocus);
        mCoordinator.onCardFocused(video.videoId);
    }

    private void watchCard(View focus) {
        View card = findVideoView(focus);

        if (card != null) {
            card.addOnAttachStateChangeListener(mCardWatcher);
            mWatchedCard = new WeakReference<>(card);
        }
    }

    private void unwatchCard() {
        View card = mWatchedCard.get();

        if (card != null) {
            card.removeOnAttachStateChangeListener(mCardWatcher);
        }

        mWatchedCard = new WeakReference<>(null);
    }

    private void hidePanel() {
        if (mPanelModel != null) {
            mPanelModel.dispose();
        }

        if (mPanel != null) {
            mPanel.setVisibility(View.GONE);
        }
    }

    @Nullable
    private Video findVideoOfFocus() {
        View focus = currentFocus();

        return focus != null ? findVideo(focus) : null;
    }

    private boolean isInOverlay(View view) {
        for (ViewParent parent = view.getParent(); parent != null; parent = parent.getParent()) {
            if (parent == mOverlay) {
                return true;
            }
        }

        return view == mOverlay;
    }

    private static void removeFromParent(@Nullable View view) {
        if (view != null && view.getParent() instanceof ViewGroup) {
            ((ViewGroup) view.getParent()).removeView(view);
        }
    }

    /**
     * The view of the card the view belongs to (see VideoCardPresenter and ModernVideoCard)
     */
    @Nullable
    static View findVideoView(View view) {
        View current = view;

        while (current != null) {
            if (current.getTag(R.id.utubot_card_video) instanceof Video) {
                return current;
            }

            ViewParent parent = current.getParent();
            current = parent instanceof View ? (View) parent : null;
        }

        return null;
    }

    /**
     * The video of the card the view belongs to
     */
    @Nullable
    static Video findVideo(View view) {
        View card = findVideoView(view);

        return card != null ? (Video) card.getTag(R.id.utubot_card_video) : null;
    }
}
