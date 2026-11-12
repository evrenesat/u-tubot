package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Application;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;

import com.liskovsoft.appupdatechecker2.core.AppVersionChecker;
import com.liskovsoft.appupdatechecker2.core.AppVersionCheckerListener;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;
import org.robolectric.util.ReflectionHelpers;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.robolectric.Shadows.shadowOf;

/**
 * The update.json of the backend (shape of the file the live server serves, hosts replaced) read by the update checker the app
 * uses: the newest version, its versionCode and changelog, and the APK chosen for the device's ABI.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotUpdateManifestTest {
    private static final String CURRENT_VERSION = "0.2.1";
    private static final long WAIT_MS = 15_000;
    private static final String HOST = "https://utubot.example.com/app/";

    private static final class Received {
        boolean isLatest;
        String versionName;
        int versionCode;
        List<String> changelog;
        List<String> downloads = new ArrayList<>();
        Exception error;
    }

    private Application mApp;
    private TinyHttpServer mServer;
    private String[] mPreviousAbis;

    @Before
    public void setUp() throws Exception {
        mApp = RuntimeEnvironment.getApplication();
        mServer = new TinyHttpServer();
        String manifest = fixture();
        mServer.on("/app/update.json", request -> new TinyHttpServer.Response(200, manifest));
        mPreviousAbis = Build.SUPPORTED_ABIS;
        installVersion(CURRENT_VERSION);
    }

    @After
    public void tearDown() {
        mServer.stop();
        ReflectionHelpers.setStaticField(Build.class, "SUPPORTED_ABIS", mPreviousAbis);
    }

    private static String fixture() throws IOException {
        try (InputStream stream = UtubotUpdateManifestTest.class.getClassLoader().getResourceAsStream("utubot/update.json")) {
            assertNotNull(stream);
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private void installVersion(String versionName) {
        PackageInfo info = new PackageInfo();
        info.packageName = mApp.getPackageName();
        info.versionName = versionName;
        shadowOf(mApp.getPackageManager()).installPackage(info);
    }

    private static void setAbi(String abi) {
        ReflectionHelpers.setStaticField(Build.class, "SUPPORTED_ABIS", new String[]{abi});
    }

    private Received check() throws InterruptedException {
        AtomicReference<Received> result = new AtomicReference<>();
        AppVersionChecker checker = new AppVersionChecker(mApp, new AppVersionCheckerListener() {
            @Override
            public void onChangelogReceived(boolean isLatestVersion, String latestVersionName, int latestVersionNumber, List<String> changelog,
                                            Uri[] downloadUris) {
                Received received = new Received();
                received.isLatest = isLatestVersion;
                received.versionName = latestVersionName;
                received.versionCode = latestVersionNumber;
                received.changelog = changelog;

                for (Uri uri : downloadUris) {
                    received.downloads.add(uri.toString());
                }

                result.set(received);
            }

            @Override
            public void onCheckError(Exception e) {
                Received received = new Received();
                received.error = e;
                result.set(received);
            }

            @Override
            public void processDownloadUrls(Uri[] downloadUrls) {
            }
        });

        checker.checkForUpdates(new Uri[]{Uri.parse("http://127.0.0.1:" + mServer.getPort() + "/app/update.json")});

        long deadline = System.currentTimeMillis() + WAIT_MS;

        while (result.get() == null && System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper();
            Thread.sleep(20);
        }

        assertNotNull("no answer from the update checker", result.get());
        assertNull(String.valueOf(result.get().error), result.get().error);

        return result.get();
    }

    @Test
    public void anOlderVersionSeesTheNewestOneWithItsCodeAndChangelog() throws Exception {
        setAbi("arm64-v8a");

        Received received = check();

        assertFalse(received.isLatest);
        assertEquals("0.2.2", received.versionName);
        assertEquals(4, received.versionCode);
        assertEquals(Arrays.asList(
                "Import setup works and Pair with code is in Settings",
                "Backend address typed by hand is validated; the token is cleared when the host changes",
                "Re-importing the same setup no longer asks to pair again"), received.changelog);
    }

    @Test
    public void theChangelogCoversEveryVersionAfterTheInstalledOne() throws Exception {
        installVersion("0.2.0");
        setAbi("arm64-v8a");

        Received received = check();

        assertEquals("0.2.2", received.versionName);
        assertEquals(6, received.changelog.size());
        assertEquals("Import setup works and Pair with code is in Settings", received.changelog.get(0));
        assertEquals("Import setup works (it failed silently in 0.2.0)", received.changelog.get(3));
        assertFalse(received.changelog.contains("First signed release. If you installed 0.1.0, uninstall it once first."));
    }

    @Test
    public void theApkOfTheDevicesAbiWins() throws Exception {
        setAbi("arm64-v8a");
        assertEquals(Arrays.asList(HOST + "u-tubot_0.2.2_arm64-v8a.apk"), check().downloads);

        setAbi("armeabi-v7a");
        assertEquals(Arrays.asList(HOST + "u-tubot_0.2.2_armeabi-v7a.apk"), check().downloads);

        setAbi("x86");
        assertEquals(Arrays.asList(HOST + "u-tubot_0.2.2_x86.apk"), check().downloads);
    }

    @Test
    public void anAbiWithoutItsOwnApkGetsTheUniversalOne() throws Exception {
        setAbi("x86_64");

        assertEquals(Arrays.asList(HOST + "u-tubot_0.2.2_universal.apk"), check().downloads);
    }

    @Test
    public void theLatestVersionNeedsNoUpdate() throws Exception {
        installVersion("0.2.2");
        setAbi("arm64-v8a");

        Received received = check();

        assertTrue(received.isLatest);
        assertEquals("0.2.2", received.versionName);
        assertEquals(4, received.versionCode);
    }

    @Test
    public void aNewerInstalledVersionNeedsNoUpdateEither() throws Exception {
        installVersion("0.3.0");
        setAbi("arm64-v8a");

        assertTrue(check().isLatest);
    }
}
