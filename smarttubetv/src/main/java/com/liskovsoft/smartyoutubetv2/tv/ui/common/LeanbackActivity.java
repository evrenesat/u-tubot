package com.liskovsoft.smartyoutubetv2.tv.ui.common;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.WindowManager;

import com.liskovsoft.smartyoutubetv2.tv.utubot.UtubotPanelController;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.SearchPresenter;
import com.liskovsoft.smartyoutubetv2.common.autoframerate.ModeSyncManager;
import com.liskovsoft.smartyoutubetv2.common.misc.GlobalKeyTranslator;
import com.liskovsoft.smartyoutubetv2.common.misc.MotherActivity;
import com.liskovsoft.smartyoutubetv2.common.misc.PlayerKeyTranslator;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.smartyoutubetv2.tv.ui.common.keyhandler.DoubleBackManager2;
import com.liskovsoft.smartyoutubetv2.tv.ui.playback.PlaybackActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.skin.SkinRegistry;
import com.liskovsoft.smartyoutubetv2.tv.ui.search.tags.SearchTagsActivity;

/**
 * This parent class contains common methods that run in every activity such as search.
 */
public abstract class LeanbackActivity extends MotherActivity {
    private static final String TAG = LeanbackActivity.class.getSimpleName();
    // A normal resume has the focus within ~0.6s (after a dialog closes), a key waits 5s before an ANR
    private static final long WINDOW_FOCUS_CHECK_MS = 1_000;
    // Several frames, so the window gets laid out unfocusable before it's made focusable again
    private static final long UNFOCUSABLE_MS = 100;
    private UriBackgroundManager mBackgroundManager;
    private ModeSyncManager mModeSyncManager;
    private DoubleBackManager2 mDoubleBackManager;
    private GlobalKeyTranslator mGlobalKeyTranslator;
    private UtubotPanelController mUtubotPanel; // Summary panel (see UtubotPanelController)
    private final Runnable sOnFinish = () -> Utils.forceFinishTheApp(this);
    private final Runnable mRestoreWindowFocus = this::restoreWindowFocusIfLost;
    private final Runnable mMakeWindowFocusable = () -> getWindow().clearFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        mBackgroundManager = new UriBackgroundManager(this);
        mModeSyncManager = ModeSyncManager.instance();
        mDoubleBackManager = new DoubleBackManager2(this);
        mGlobalKeyTranslator = this instanceof PlaybackActivity ?
                new PlayerKeyTranslator(this) :
                new GlobalKeyTranslator(this);
        mGlobalKeyTranslator.apply();
        mUtubotPanel = this instanceof PlaybackActivity ? null : new UtubotPanelController(this);
    }

    @Override
    protected void initTheme() {
        super.initTheme();
        // A screen the skin has no activity of its own for (see Skin)
        SkinRegistry.instance().getAppliedSkin().onThemeApplied(this);
    }

    @Override
    public boolean onSearchRequested() {
        SearchPresenter.instance(this).startSearch(null);
        return true;
    }

    @SuppressLint("RestrictedApi")
    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        Log.d(TAG, event);

        if (mUtubotPanel != null && mUtubotPanel.dispatchKeyEvent(event)) {
            return true;
        }

        KeyEvent newEvent = mGlobalKeyTranslator.translate(event);
        return super.dispatchKeyEvent(newEvent);
    }

    public UriBackgroundManager getBackgroundManager() {
        return mBackgroundManager;
    }

    @Override
    protected void onStart() {
        super.onStart();

        mBackgroundManager.onStart();
    }

    @Override
    protected void onResume() {
        super.onResume();

        // PIP fix: While entering/exiting PIP mode only Pause/Resume is called

        mGlobalKeyTranslator.apply(); // adapt to state changes (like enter/exit from PIP mode)

        mModeSyncManager.restore(this);

        // Replaced by the activity of another skin (see Skins)
        if (!isFinishing()) {
            getViewManager().addTop(this);
        }

        Utils.postDelayed(mRestoreWindowFocus, WINDOW_FOCUS_CHECK_MS);

        if (mUtubotPanel != null) {
            mUtubotPanel.onResume();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();

        Utils.removeCallbacks(mRestoreWindowFocus);

        if (mUtubotPanel != null) {
            mUtubotPanel.onPause();
        }
    }

    /**
     * A link opened over this activity starts the splash in its own task, which hands straight back here (singleInstance).
     * WindowManager may drop the focus during that hop and never give it back (seen on Android 14): the activity shows,
     * but every key times out into an ANR ("does not have a focused window"). Changing the focusability of the window
     * makes WindowManager look for the focus again.
     */
    private void restoreWindowFocusIfLost() {
        if (isFinishing() || hasWindowFocus() || isInPictureInPictureMode()) {
            return;
        }

        Log.d(TAG, "%s has no window focus. Making WindowManager look for it again...", getClass().getSimpleName());

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        Utils.postDelayed(mMakeWindowFocusable, UNFOCUSABLE_MS);
    }

    @Override
    protected void onStop() {
        super.onStop();
        mBackgroundManager.onStop();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        mBackgroundManager.onDestroy();

        if (mUtubotPanel != null) {
            mUtubotPanel.onDestroy();
        }
    }

    @Override
    public void finish() {
        // user pressed back key
        if (!getViewManager().hasParentView(this)) {
            switch (getGeneralData().getAppExitShortcut()) {
                case GeneralData.EXIT_DOUBLE_BACK:
                    mDoubleBackManager.enableDoubleBackExit(this::finishTheApp);
                    break;
                case GeneralData.EXIT_SINGLE_BACK:
                    finishTheApp();
                    break;
            }
        } else if (this instanceof PlaybackActivity) {
            switch (getGeneralData().getPlayerExitShortcut()) {
                case GeneralData.EXIT_DOUBLE_BACK:
                    mDoubleBackManager.enableDoubleBackExit(this::finishReally);
                    break;
                case GeneralData.EXIT_SINGLE_BACK:
                    finishReally();
                    break;
            }
        } else if (isSearchScreen()) {
            switch (getGeneralData().getSearchExitShortcut()) {
                case GeneralData.EXIT_DOUBLE_BACK:
                    mDoubleBackManager.enableDoubleBackExit(this::finishReally);
                    break;
                case GeneralData.EXIT_SINGLE_BACK:
                    finishReally();
                    break;
            }
        } else {
            finishReally();
        }
    }

    /**
     * Search screens share the search exit shortcut.
     */
    protected boolean isSearchScreen() {
        return this instanceof SearchTagsActivity;
    }

    @Override
    public void finishReally() {
        // Mandatory line. Fix un-proper view order (especially for playback view).
        getViewManager().startParentView(this);
        super.finishReally();
    }

    private void finishTheApp() {
        getViewManager().addOnFinish(sOnFinish);

        Utils.properlyFinishTheApp(this);
    }
}
