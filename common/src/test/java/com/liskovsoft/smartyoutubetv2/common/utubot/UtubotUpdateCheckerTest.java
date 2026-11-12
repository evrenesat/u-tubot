package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;
import android.net.Uri;

import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

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
}
