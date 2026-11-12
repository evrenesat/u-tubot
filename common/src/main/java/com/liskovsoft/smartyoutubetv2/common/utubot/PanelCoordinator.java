package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import java.util.function.LongSupplier;

/**
 * When the passive side panel is up, and for which card. The rule: the panel shows only while a card of the list has the focus
 * and the user's attention is on the list. Focus on anything else (the sidebar, a section header, nothing while a list loads or
 * is empty), a card that goes away, the activity pausing (the player opens) or the Summary view opening hides the panel and drops
 * its request, so it never shows the summary of a card from another screen.
 */
public final class PanelCoordinator {
    public interface Output {
        /**
         * The panel is up with the card's title and "Waiting…". Anything in flight is to be cancelled.
         */
        void showWaiting(String key);

        /**
         * The card kept the focus for the whole pause: the request starts
         */
        void showSettled(String key);

        /**
         * The panel goes and its content is cleared. Anything in flight is to be cancelled.
         */
        void hide();
    }

    private final FocusDebouncer mDebouncer;
    private final Output mOutput;
    private boolean mIsEnabled;
    private boolean mIsResumed;
    private boolean mIsModalOpen;
    private boolean mIsVisible;
    private String mCurrent;

    public PanelCoordinator(UtubotScheduler scheduler, LongSupplier delayMs, Output output) {
        mOutput = output;
        mDebouncer = new FocusDebouncer(scheduler, delayMs, new FocusDebouncer.Listener() {
            @Override
            public void onPending(String key) {
                mCurrent = key;
                mIsVisible = true;
                mOutput.showWaiting(key);
            }

            @Override
            public void onSettled(String key) {
                mOutput.showSettled(key);
            }
        });
    }

    /**
     * The panel mode (Settings, u-tubot, Summary panel) is on
     */
    public void setEnabled(boolean enabled) {
        mIsEnabled = enabled;

        if (!enabled) {
            hide();
        }
    }

    public void onResume() {
        mIsResumed = true;
    }

    public void onPause() {
        mIsResumed = false;
        hide();
    }

    /**
     * The Summary view is up (or gone): the panel stays out of its way
     */
    public void setModalOpen(boolean open) {
        mIsModalOpen = open;

        if (open) {
            hide();
        }
    }

    /**
     * A card of the list took the focus
     */
    public void onCardFocused(@Nullable String videoId) {
        if (videoId == null) {
            onNothingFocused();
        } else if (isActive()) {
            mDebouncer.focus(videoId);
        }
    }

    /**
     * The focus is on something that isn't a card (the sidebar, a header), or on nothing (e.g. while a list reloads)
     */
    public void onNothingFocused() {
        if (!mIsModalOpen) {
            hide();
        }
    }

    /**
     * A card left the screen (the list was replaced)
     */
    public void onCardGone(@Nullable String videoId) {
        if (videoId != null && videoId.equals(mCurrent)) {
            hide();
        }
    }

    /**
     * The user sent the panel away (Back): it goes and the card is forgotten, so it comes again with the next card that keeps the
     * focus for the pause. The panel mode stays on.
     *
     * @return the panel was up
     */
    public boolean dismiss() {
        boolean wasVisible = mIsVisible;
        hide();

        return wasVisible;
    }

    /**
     * The user keeps pressing keys: the pause starts again
     */
    public void onKeyActivity() {
        mDebouncer.touch();
    }

    public boolean isVisible() {
        return mIsVisible;
    }

    @Nullable
    public String getCurrentKey() {
        return mIsVisible ? mCurrent : null;
    }

    private boolean isActive() {
        return mIsEnabled && mIsResumed && !mIsModalOpen;
    }

    private void hide() {
        mDebouncer.cancel();
        mCurrent = null;

        if (mIsVisible) {
            mIsVisible = false;
            mOutput.hide();
        }
    }
}
