package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Application;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsItem;
import com.liskovsoft.smartyoutubetv2.common.misc.AppDataSourceManager;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.tv.R;

import org.junit.Assume;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import java.io.IOException;
import java.nio.file.Paths;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

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

    /**
     * Every address the flavor shows or fetches is its own repository's (u·tubot is not Electric Eel or SmartTube, which are only
     * credited), the releases of its notes are its own tags, there are no donations and no server to submit diagnostics to
     */
    @Test
    public void theFlavorShowsOnlyItsOwnAddresses() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        Context context = RuntimeEnvironment.getApplication();
        String repository = "https://github.com/evrenesat/u-tubot";
        int[] addresses = {
                com.liskovsoft.smartyoutubetv2.common.R.string.about_feedback_url,
                com.liskovsoft.smartyoutubetv2.common.R.string.about_releases_url,
                com.liskovsoft.smartyoutubetv2.common.R.string.about_git_repository_url,
                com.liskovsoft.smartyoutubetv2.common.R.string.releases_url,
                com.liskovsoft.smartyoutubetv2.common.R.string.sources_url,
                com.liskovsoft.smartyoutubetv2.common.R.string.web_site_url,
                com.liskovsoft.smartyoutubetv2.common.R.string.release_notes_url,
        };

        for (int address : addresses) {
            String url = context.getString(address);

            assertTrue(context.getResources().getResourceEntryName(address) + " is " + url, url.startsWith(repository)
                    || url.startsWith("https://api.github.com/repos/evrenesat/u-tubot/"));
        }

        assertEquals(repository + "/issues", context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.about_feedback_url));
        assertEquals("https://api.github.com/repos/evrenesat/u-tubot/releases?per_page=10",
                context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.release_notes_url));
        assertEquals("only the tags of the app's releases", "utubot-v",
                context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.release_notes_tag_prefix));
        assertEquals("no donation", "", context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.about_donation_url));
        assertEquals("no Submit data server", "", context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.submit_data_url));
        assertEquals("no donation list", 0, Helpers.getMap(context, com.liskovsoft.smartyoutubetv2.common.R.array.donations).size());

        for (String feedback : Helpers.getMap(context, com.liskovsoft.smartyoutubetv2.common.R.array.feedback).values()) {
            assertTrue("feedback goes to " + feedback, feedback.startsWith(repository));
        }
    }

    /**
     * The credit names the two projects u·tubot is built on, with their repositories: the only upstream addresses
     */
    @Test
    public void theCreditNamesTheBaseProjects() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        Context context = RuntimeEnvironment.getApplication();

        assertEquals("Based on Electric Eel and SmartTube", context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.about_credit));

        java.util.Map<String, String> credits = Helpers.getMap(context, com.liskovsoft.smartyoutubetv2.common.R.array.about_credits);

        assertEquals("https://github.com/cygnusx-1-org/electriceel", credits.get("Electric Eel"));
        assertEquals("https://github.com/yuliskov/SmartTube", credits.get("SmartTube"));
        assertEquals(2, credits.size());
    }

    @Test
    public void theNameIsTheFlavors() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        Context context = RuntimeEnvironment.getApplication();

        assertEquals("u·tubot", context.getString(R.string.app_name));
        assertEquals("the title of the browse screen", "u·tubot", context.getString(R.string.browse_title));
        assertFalse(context.getString(R.string.app_name).contains("Electric"));
    }

    /**
     * The Settings tile of the layer has its own icon (the symbol), not the crossed-out "AI" that Content filtering uses
     */
    @Test
    public void theSettingsTileHasTheSymbolIcon() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        Context context = RuntimeEnvironment.getApplication();
        SettingsItem tile = null;

        for (SettingsItem item : AppDataSourceManager.instance().getSettingItems(context)) {
            if (context.getString(com.liskovsoft.smartyoutubetv2.common.R.string.utubot_title).equals(item.title)) {
                tile = item;
            }
        }

        assertTrue("no u·tubot tile in Settings", tile != null);
        assertEquals(com.liskovsoft.smartyoutubetv2.common.R.drawable.settings_utubot, tile.imageResId);
        assertNotEquals(com.liskovsoft.smartyoutubetv2.common.R.drawable.settings_aislist, tile.imageResId);
    }

    /**
     * The icon is white on transparent with the canvas and the padding of the About icon (assets/brand/render.py draws it)
     */
    @Test
    public void theSettingsIconMatchesTheAboutIconsCanvasAndPadding() throws IOException {
        PngPixels icon = settingsIcon("settings_utubot.png");
        PngPixels about = settingsIcon("settings_about.png");

        assertEquals(about.width, icon.width);
        assertEquals(about.height, icon.height);
        int[] iconBounds = icon.visibleBounds();
        int[] aboutBounds = about.visibleBounds();
        assertEquals("padding above", aboutBounds[1], iconBounds[1]);
        assertEquals("padding below", about.height - aboutBounds[3], icon.height - iconBounds[3]);
        assertTrue("the shape fills the width the canvas leaves", iconBounds[2] - iconBounds[0] > icon.width * 3 / 4);
        boolean hasHole = false;

        for (int y = 0; y < icon.height; y++) {
            for (int x = 0; x < icon.width; x++) {
                assertTrue("not white at " + x + "," + y, icon.alpha(x, y) == 0 || icon.rgb(x, y) == 0xFFFFFF);
                hasHole |= icon.alpha(x, y) == 0 && x > iconBounds[0] + icon.width / 4 && x < iconBounds[2] - icon.width / 4
                        && y > iconBounds[1] + icon.height / 4 && y < iconBounds[3] - icon.height / 4;
            }
        }

        assertTrue("the u is a hole in the shape", hasHole);
    }

    private static PngPixels settingsIcon(String name) throws IOException {
        // The unit tests run in the module's directory
        return PngPixels.read(Paths.get("..", "common", "src", "main", "res", "drawable-nodpi", name));
    }
}
