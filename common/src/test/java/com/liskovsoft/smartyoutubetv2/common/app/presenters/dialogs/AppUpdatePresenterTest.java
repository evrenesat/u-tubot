package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs;

import android.app.Activity;
import android.content.Context;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;
import com.liskovsoft.smartyoutubetv2.common.utubot.StoredSettings;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotUpdateChecker;

import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;
import org.robolectric.shadows.ShadowToast;
import org.robolectric.util.ReflectionHelpers;

import java.io.File;
import java.net.UnknownHostException;
import java.time.Duration;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class AppUpdatePresenterTest {
    private Activity mActivity;
    private CountingPresenter mPresenter;

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        // The stutubot flavor checks only the update URL of an imported setup
        UtubotSettings.instance(mActivity).setUpdateUrl("https://updates.example.com/app/update.json");
        mPresenter = new CountingPresenter(mActivity);
    }

    @After
    public void tearDown() {
        AppUpdatePresenter.unhold();
    }

    /**
     * u-tubot without an imported setup has no update source: nothing is checked
     */
    @Test
    public void noUpdateSource_noCheck() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        UtubotSettings.instance(mActivity).setUpdateUrl("");

        mPresenter.start(true);
        idle(60_000);

        assertEquals(0, mPresenter.mChecks);
    }

    /**
     * A TV set up by hand on 0.2.0 (backend typed under Advanced, no update address ever stored) and then upgraded: the manual check
     * and the automatic one both use the update file of the backend
     */
    @Test
    public void backendWithoutAStoredUpdateUrl_bothChecksUseTheDerivedOne() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        useStoredBackendOnly("http://10.0.0.5:8790/");
        mPresenter = new CountingPresenter(mActivity);

        assertArrayEquals(new String[]{"http://10.0.0.5:8790/app/update.json"}, mPresenter.getUpdateUrls());

        mPresenter.start(true);
        assertEquals(1, mPresenter.mChecks);
        assertNull("the manual check must not say there is no update source", ShadowToast.getTextOfLatestToast());
        assertEquals("the automatic check consults the same address", "http://10.0.0.5:8790/app/update.json",
                UtubotSettings.instance(mActivity).getUpdateUrl());
    }

    /**
     * A setup that says nothing about updates is stored as such: no check, however the backend looks
     */
    @Test
    public void setupWithoutUpdateUrl_noCheck() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("https://utubot.example.com");
        settings.setUpdateUrl("");

        mPresenter.start(true);

        assertEquals(0, mPresenter.getUpdateUrls().length);
        assertEquals(0, mPresenter.mChecks);
        assertEquals("No update source: import your server's setup first", ShadowToast.getTextOfLatestToast());
    }

    /**
     * Only the backend stored, as an upgrade from 0.2.0 leaves it
     */
    private void useStoredBackendOnly(String backend) {
        StoredSettings.cleared(UtubotSettings.instance(mActivity)).putString("url", backend).commit();
    }

    /**
     * Failing: tried again after 10 s and after 20 s more, then the error is shown
     */
    @Test
    public void forcedCheck_retriedTwice_thenError() {
        mPresenter.start(true);
        fail();

        idle(9_999);
        assertEquals(1, mPresenter.mChecks);
        idle(1);
        assertEquals(2, mPresenter.mChecks);
        fail();

        idle(19_999);
        assertEquals(2, mPresenter.mChecks);
        idle(1);
        assertEquals(3, mPresenter.mChecks);
        assertNull(ShadowToast.getTextOfLatestToast());
        fail();

        idle(60_000);
        assertEquals(3, mPresenter.mChecks);
        assertEquals("Update error: try again later", ShadowToast.getTextOfLatestToast());
    }

    /**
     * A downloaded apk of another package (a test build's update) is a failure, not a check that never ends
     */
    @Test
    public void forcedCheck_rejectedApk_retried() {
        mPresenter.start(true);
        new AppUpdateChecker(mActivity, mPresenter).onApkDownloaded(new File(mActivity.getCacheDir(), "update.apk").getPath());

        idle(10_000);
        assertEquals(2, mPresenter.mChecks);
    }

    /**
     * Up to date on a retry: said so, no more retries
     */
    @Test
    public void forcedCheck_latestVersionOnRetry_noMoreRetries() {
        mPresenter.start(true);
        fail();
        idle(10_000);

        mPresenter.onUpdateError(new IllegalStateException(AppUpdateCheckerListener.LATEST_VERSION));

        idle(60_000);
        assertEquals(2, mPresenter.mChecks);
        assertEquals("You're using the latest version", ShadowToast.getTextOfLatestToast());
    }

    /**
     * Pressed again while waiting to retry: the running check goes on, not a second one
     */
    @Test
    public void forcedCheck_pressedAgainWhileWaiting_ignored() {
        mPresenter.start(true);
        fail();

        mPresenter.start(true);
        mPresenter.start(false);
        assertEquals(1, mPresenter.mChecks);

        idle(10_000);
        assertEquals(2, mPresenter.mChecks);
    }

    /**
     * The app finished while waiting to retry: no retry, no message
     */
    @Test
    public void forcedCheck_appFinishedWhileWaiting_noRetry() {
        mPresenter.start(true);
        fail();
        mPresenter.stopForceCheck(); // by unhold()

        idle(60_000);
        assertEquals(1, mPresenter.mChecks);
        assertNull(ShadowToast.getTextOfLatestToast());
    }

    /**
     * An update that was found while the player was open (or the app in the background) is not dropped: the built-in flavor is told to
     * offer it again soon. Nothing is shown meanwhile.
     */
    @Test
    public void anUpdateFoundWhilePlaying_isDeferredNotShown() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        mPresenter.mCanShowDialog = false;

        mPresenter.onUpdateFound("0.9.0", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");

        assertEquals(1, mPresenter.mDeferred);
        assertFalse(AppDialogPresenter.instance(mActivity).isDialogShown());
    }

    @Test
    public void anUpdateFoundWhilePlaying_isDeferredAlsoForAForcedCheck() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        mPresenter.mCanShowDialog = false;
        mPresenter.start(true);

        mPresenter.onUpdateFound("0.9.0", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");

        assertEquals(1, mPresenter.mDeferred);
    }

    /**
     * The built-in flavor downloads only from https (or private) addresses
     */
    @Test
    public void theBuiltInFlavorChecksWithTheGuardedChecker() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());

        assertTrue(ReflectionHelpers.getField(new AppUpdatePresenter(mActivity), "mUpdateChecker") instanceof UtubotUpdateChecker);
    }

    private void fail() {
        mPresenter.onUpdateError(new UnknownHostException("github.com"));
    }

    private static void idle(long ms) {
        ShadowLooper.shadowMainLooper().idleFor(Duration.ofMillis(ms));
    }

    private static class CountingPresenter extends AppUpdatePresenter {
        private int mChecks;
        private int mDeferred;
        private boolean mCanShowDialog = true;

        CountingPresenter(Context context) {
            super(context);
        }

        @Override
        boolean canShowUpdateDialog() {
            return mCanShowDialog;
        }

        @Override
        void deferUpdate() {
            mDeferred++;
        }

        @Override
        void forceCheck() {
            mChecks++;
        }
    }
}
