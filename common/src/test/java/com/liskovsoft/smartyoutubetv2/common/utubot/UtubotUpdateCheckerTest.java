package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.content.pm.PackageInfo;
import android.net.Uri;

import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowPackageManager;

import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.robolectric.Shadows.shadowOf;

/**
 * The APK addresses of update.json are held to the rule of the backend address before the shared downloader sees them: https, or
 * http for a private host. The shared checker itself only asks Android whether a string is a URL.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotUpdateCheckerTest {
    private static final String APK = "/app/u-tubot_0.9.0_universal.apk";
    private Activity mActivity;
    private Exception mError;
    private int mFound;

    private final AppUpdateCheckerListener mListener = new AppUpdateCheckerListener() {
        @Override
        public void onUpdateFound(String versionName, List<String> changelog, String apkPath) {
            mFound++;
        }

        @Override
        public void onUpdateError(Exception error) {
            mError = error;
        }
    };

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
    }

    @Test
    public void httpsIsAllowedForAnyHost() {
        assertTrue(UtubotUpdateChecker.isAllowedDownload("https://utubot.example.com" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("https://github.com/owner/u-tubot/releases/download/v0.9.0/u-tubot_0.9.0_universal.apk"));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("HTTPS://203.0.113.9:8443" + APK));
    }

    @Test
    public void httpIsAllowedForPrivateHostsOnly() {
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://10.0.0.5:8790" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://192.168.1.20" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://127.0.0.1:18790" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://100.101.102.103" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://utubot.tail0fad23.ts.net" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://nas.local" + APK));
        assertTrue(UtubotUpdateChecker.isAllowedDownload("http://[::1]:8790" + APK));

        assertFalse(UtubotUpdateChecker.isAllowedDownload("http://utubot.example.com" + APK));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("http://203.0.113.9" + APK));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("http://github.com/owner/repo/u-tubot.apk"));
        assertFalse("a public name that only starts like a private one", UtubotUpdateChecker.isAllowedDownload("http://10.0.0.5.evil.net" + APK));
        assertFalse("the private host is only the userinfo", UtubotUpdateChecker.isAllowedDownload("http://10.0.0.5@evil.net" + APK));
        assertFalse("a private name in the path", UtubotUpdateChecker.isAllowedDownload("http://evil.net/10.0.0.5" + APK));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("http://172.32.0.1" + APK));
    }

    @Test
    public void otherSchemesAndGarbageAreRefused() {
        assertFalse(UtubotUpdateChecker.isAllowedDownload("file:///sdcard/Download/u-tubot.apk"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("content://com.example.provider/u-tubot.apk"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("ftp://10.0.0.5/u-tubot.apk"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("javascript:alert(1)"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("/app/u-tubot.apk"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("u-tubot.apk"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload("https://"));
        assertFalse(UtubotUpdateChecker.isAllowedDownload(""));
        assertFalse(UtubotUpdateChecker.isAllowedDownload(null));
    }

    @Test
    public void aMixedListKeepsTheAllowedAddressesInTheirOrder() {
        Uri secure = Uri.parse("https://utubot.example.com" + APK);
        Uri lan = Uri.parse("http://10.0.0.5:8790" + APK);

        Uri[] allowed = UtubotUpdateChecker.allowedDownloads(new Uri[]{
                Uri.parse("http://utubot.example.com" + APK),
                lan,
                Uri.parse("file:///sdcard/u-tubot.apk"),
                null,
                secure});

        assertArrayEquals(new Uri[]{lan, secure}, allowed);
    }

    @Test
    public void anUpdateThatOffersOnlyUnsafeAddressesIsAnErrorNotADownload() {
        UtubotUpdateChecker checker = new UtubotUpdateChecker(mActivity, mListener);

        checker.onChangelogReceived(false, "0.9.0", 9000, Collections.singletonList("Fixes"),
                new Uri[]{Uri.parse("http://utubot.example.com" + APK), Uri.parse("file:///sdcard/u-tubot.apk")});

        assertEquals(UtubotUpdateChecker.NO_SAFE_DOWNLOAD, mError.getMessage());
        assertEquals(0, mFound);
    }

    @Test
    public void anEmptyListIsTheSameError() {
        UtubotUpdateChecker checker = new UtubotUpdateChecker(mActivity, mListener);

        checker.onChangelogReceived(false, "0.9.0", 9000, Collections.singletonList("Fixes"), new Uri[0]);

        assertEquals(UtubotUpdateChecker.NO_SAFE_DOWNLOAD, mError.getMessage());
    }

    @Test
    public void upToDateNeedsNoAddressAndIsReportedAsBefore() {
        UtubotUpdateChecker checker = new UtubotUpdateChecker(mActivity, mListener);

        checker.onChangelogReceived(true, "0.2.2", 4, null, new Uri[]{Uri.parse("http://utubot.example.com" + APK)});

        assertEquals(AppUpdateCheckerListener.LATEST_VERSION, mError.getMessage());
        assertEquals(0, mFound);
    }

    /**
     * The channel's versionCode decides (u-tubot#80): a version name can be shared while the code already grew, and a channel
     * that offers a higher code is an update even when the shared checker judged the names equal.
     */
    @Test
    public void theVersionCodeDecidesWhenBothAreKnown() {
        assertTrue("higher code, same name", UtubotUpdateChecker.isNewer(3010, 3011, false));
        assertTrue("higher code, older name", UtubotUpdateChecker.isNewer(3010, 3011, false));
        assertFalse("same code, newer name", UtubotUpdateChecker.isNewer(3010, 3010, true));
        assertFalse("older code, newer name", UtubotUpdateChecker.isNewer(3010, 3009, true));
        assertFalse("same code, same name", UtubotUpdateChecker.isNewer(3010, 3010, false));
    }

    @Test
    public void aManifestWithoutACodeFallsBackToTheNameComparison() {
        assertTrue("no channel code", UtubotUpdateChecker.isNewer(3010, 0, true));
        assertFalse("no channel code, older name", UtubotUpdateChecker.isNewer(3010, 0, false));
        assertTrue("no installed code", UtubotUpdateChecker.isNewer(0, 3011, true));
    }

    @Test
    public void theInstalledCodeIsReadFromTheApp() throws Exception {
        installVersionCode(3010);

        assertEquals(3010, new UtubotUpdateChecker(mActivity, mListener).getInstalledVersionCode());
    }

    /**
     * The shared checker can judge a higher code's version name equal (or older): the flavor still reports it as an update.
     * An empty address list shows which path was taken (safe-address error vs "latest version").
     */
    @Test
    public void aHigherCodeWithTheSameNameIsAnUpdateNotTheLatestVersion() throws Exception {
        installVersionCode(3010);
        UtubotUpdateChecker checker = new UtubotUpdateChecker(mActivity, mListener);

        checker.onChangelogReceived(true, "0.3.10", 3011, null, new Uri[0]);

        assertEquals(UtubotUpdateChecker.NO_SAFE_DOWNLOAD, mError.getMessage());
    }

    @Test
    public void anEqualOrOlderCodeWithANewerNameIsNotAnUpdate() throws Exception {
        installVersionCode(3010);
        UtubotUpdateChecker checker = new UtubotUpdateChecker(mActivity, mListener);

        checker.onChangelogReceived(false, "0.3.11", 3010, Collections.singletonList("Fixes"), new Uri[0]);

        assertEquals(AppUpdateCheckerListener.LATEST_VERSION, mError.getMessage());
        assertEquals(0, mFound);
    }

    private void installVersionCode(int versionCode) throws Exception {
        PackageInfo info = mActivity.getPackageManager().getPackageInfo(mActivity.getPackageName(), 0);
        info.versionCode = versionCode;
        ShadowPackageManager manager = shadowOf(mActivity.getPackageManager());
        manager.installPackage(info);
    }
}
