package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs;

import android.app.Activity;
import android.content.Context;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

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

import java.io.File;
import java.net.UnknownHostException;
import java.time.Duration;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

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

    private void fail() {
        mPresenter.onUpdateError(new UnknownHostException("github.com"));
    }

    private static void idle(long ms) {
        ShadowLooper.shadowMainLooper().idleFor(Duration.ofMillis(ms));
    }

    private static class CountingPresenter extends AppUpdatePresenter {
        private int mChecks;

        CountingPresenter(Context context) {
            super(context);
        }

        @Override
        void forceCheck() {
            mChecks++;
        }
    }
}
