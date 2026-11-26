package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs;

import android.app.Activity;
import android.content.Context;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;
import com.liskovsoft.appupdatechecker2.other.SettingsManager;
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
import java.util.List;

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
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUpdateUrl("https://updates.example.com/app/update.json");
        settings.setDismissedUpdateVersion("");
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

    /**
     * The automatic check asks the channel on the schedule even when the shared checker's short "recently checked" window says
     * no (u-tubot#80: the check runs on app start and on the schedule). Notifications control it.
     */
    @Test
    public void theAutomaticCheckAlwaysAsksTheChannelWhenNotificationsAreOn() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        SettingsManager settings = new SettingsManager(mActivity);
        settings.setMinIntervalMs(SettingsManager.CHECK_INTERVAL_DEFAULT_MS);
        settings.setLastCheckedMs(System.currentTimeMillis());

        assertTrue(mPresenter.startAutomatic());
        assertEquals("not gated by the shared checker's 60 second check window", 1, mPresenter.mChecks);

        settings.setMinIntervalMs(-1);
        assertFalse(mPresenter.startAutomatic());
        assertEquals("notifications off: no check", 1, mPresenter.mChecks);

        settings.setMinIntervalMs(SettingsManager.CHECK_INTERVAL_DEFAULT_MS);
        UtubotSettings.instance(mActivity).setUpdateUrl("");
        assertFalse("no update source", mPresenter.startAutomatic());
        assertEquals(1, mPresenter.mChecks);
    }

    /**
     * A dismissed automatic notification stays silent for that version and comes back with the next one; the manual check shows
     * even the dismissed version, as the user asked for it.
     */
    @Test
    public void aDismissedVersionIsNotOfferedAgainUntilANewerOne() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        UtubotSettings.instance(mActivity).setDismissedUpdateVersion("0.9.0");

        mPresenter.onUpdateFound("0.9.0", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");
        assertEquals(0, mPresenter.mShown);

        mPresenter.onUpdateFound("0.9.1", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");
        assertEquals(1, mPresenter.mShown);

        mPresenter.start(true);
        mPresenter.onUpdateFound("0.9.0", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");
        assertEquals("the manual check shows it", 2, mPresenter.mShown);
    }

    @Test
    public void aDismissedNameWithAHigherCodeIsANewVersion() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        UtubotSettings.instance(mActivity).setDismissedUpdate("0.3.10", 3011);

        mPresenter.mOfferedVersionCode = 3011;
        mPresenter.onUpdateFound("0.3.10", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");
        assertEquals("the dismissed build is silent", 0, mPresenter.mShown);

        mPresenter.mOfferedVersionCode = 3012;
        mPresenter.onUpdateFound("0.3.10", java.util.Collections.singletonList("Fixes"), "/cache/update.apk");
        assertEquals("the same name with a higher code is a new version", 1, mPresenter.mShown);
    }

    @Test
    public void theDismissedVersionIsTheOnlyOneSuppressed() {
        UtubotSettings settings = UtubotSettings.instance(mActivity);

        assertFalse(settings.isUpdateDismissed("0.9.0"));
        settings.setDismissedUpdate("0.9.0", 900);

        assertTrue(settings.isUpdateDismissed("0.9.0", 900));
        assertTrue("a stored address with spaces is the same version", settings.isUpdateDismissed(" 0.9.0 ", 900));
        assertFalse("a higher code under the same name", settings.isUpdateDismissed("0.9.0", 901));
        assertFalse(settings.isUpdateDismissed("0.9.1", 900));
        assertFalse(settings.isUpdateDismissed(""));
    }

    @Test
    public void aNewUpdateUrlClearsTheDismissedVersion() {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setDismissedUpdate("0.9.0", 900);

        settings.setUpdateUrl("https://other.example.com/app/update.json");

        assertFalse("the dismissed version belongs to the old channel", settings.isUpdateDismissed("0.9.0", 900));
        assertEquals("", settings.getDismissedUpdateVersion());
    }

    private void fail() {
        mPresenter.onUpdateError(new UnknownHostException("github.com"));
    }

    @Test
    public void developmentModeFollowsTheSetting() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        UtubotSettings.instance(mActivity).setDevelopmentMode(true);
        assertTrue(mPresenter.isDevelopmentMode());

        UtubotSettings.instance(mActivity).setDevelopmentMode(false);
        assertFalse(mPresenter.isDevelopmentMode());
    }

    private static void idle(long ms) {
        ShadowLooper.shadowMainLooper().idleFor(Duration.ofMillis(ms));
    }

    private static class CountingPresenter extends AppUpdatePresenter {
        private int mChecks;
        private int mDeferred;
        private int mShown;
        private int mOfferedVersionCode;
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

        @Override
        int offeredVersionCode() {
            return mOfferedVersionCode;
        }

        @Override
        void showUpdateDialog(String versionName, List<String> changelog, String apkPath) {
            // The real dialog needs the UI; the call the presenter makes is what is counted
            if (!canShowUpdateDialog()) {
                deferUpdate();
                return;
            }

            mShown++;
        }
    }
}
