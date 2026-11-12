package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ProviderInfo;
import android.net.Uri;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.sharedutils.helpers.FileHelpers;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.util.Arrays;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * What the update flow needs from the manifest: the permission to start the installer, and the file provider that hands it the
 * downloaded apk
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotUpdateInstallTest {
    @Test
    public void theAppMayRequestPackageInstalls() throws Exception {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        PackageInfo info = activity.getPackageManager().getPackageInfo(activity.getPackageName(), PackageManager.GET_PERMISSIONS);

        assertNotNull(info.requestedPermissions);
        assertTrue(Arrays.asList(info.requestedPermissions).contains(Manifest.permission.REQUEST_INSTALL_PACKAGES));
    }

    @Test
    public void theUpdateFileProviderServesTheDownloadedApk() throws Exception {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();
        String authority = activity.getPackageName() + ".update_provider";
        ProviderInfo provider = activity.getPackageManager().resolveContentProvider(authority, 0);

        assertNotNull(provider);
        assertTrue(provider.grantUriPermissions);

        File cacheDir = FileHelpers.getCacheDir(activity);
        assertNotNull(cacheDir);
        Uri uri = FileHelpers.getFileUri(activity, new File(cacheDir, "update.apk").getPath());

        assertNotNull("the apk's folder isn't covered by the provider's paths", uri);
        assertEquals(authority, uri.getAuthority());
    }

    @Test
    public void theUpdateCheckIsOnByDefault() {
        Activity activity = Robolectric.buildActivity(Activity.class).setup().get();

        assertTrue(new AppUpdateChecker(activity, null).isUpdateCheckEnabled());
    }
}
