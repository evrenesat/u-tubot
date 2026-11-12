package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Application;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.tv.R;

import org.junit.Assume;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotBrandingTest {
    /**
     * The application's own label and icons: what the system installer, Settings and the recents show for the flavor. The label is a
     * literal in the manifest (an installer that reads a package file without its resources still has it, instead of showing the
     * application class name), the same text as app_name.
     */
    @Test
    public void theApplicationHasItsFlavorsLabelAndIcons() throws Exception {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        Application application = RuntimeEnvironment.getApplication();
        PackageManager packageManager = application.getPackageManager();
        ApplicationInfo info = packageManager.getApplicationInfo(application.getPackageName(), 0);

        assertEquals("u·tubot", info.loadLabel(packageManager).toString());
        assertEquals("the literal in src/stutubot/AndroidManifest.xml has drifted from app_name", application.getString(R.string.app_name),
                String.valueOf(info.nonLocalizedLabel));
        assertNotEquals("no icon on <application>", 0, info.icon);
        assertNotEquals("no banner on <application>", 0, info.banner);
        assertNotEquals("no logo on <application>", 0, info.logo);
    }
}
