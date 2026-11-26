package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Application;
import android.content.Intent;
import android.content.pm.FeatureInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;

/**
 * A tablet has no leanback system feature (and maybe no USB host): the package must still install there and show a launcher icon
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotTabletManifestTest {
    private static final String LEANBACK = "android.software.leanback";
    private static final String USB_HOST = "android.hardware.usb.host";
    private static final String BLUETOOTH = "android.hardware.bluetooth";

    @Test
    public void noFeatureOnlyATvHasIsRequired() throws PackageManager.NameNotFoundException {
        Application application = RuntimeEnvironment.getApplication();
        PackageInfo info = application.getPackageManager().getPackageInfo(application.getPackageName(), PackageManager.GET_CONFIGURATIONS);

        if (info.reqFeatures == null) {
            return;
        }
        for (FeatureInfo feature : info.reqFeatures) {
            boolean required = (feature.flags & FeatureInfo.FLAG_REQUIRED) != 0;
            assertFalse(feature.name + " is required: the package would not install on a tablet",
                    required && (LEANBACK.equals(feature.name) || USB_HOST.equals(feature.name) || BLUETOOTH.equals(feature.name)));
        }
    }

    @Test
    public void theAppHasAPhoneLauncherEntry() {
        Application application = RuntimeEnvironment.getApplication();
        Intent launcher = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setPackage(application.getPackageName());

        assertNotNull("no LAUNCHER activity: no icon on a tablet", application.getPackageManager().resolveActivity(launcher, 0));
    }
}
