package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.app.Application;
import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.AboutSimpleSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.AppDialogView;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import org.junit.After;
import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * Settings, About of the flavor: its own rows and addresses, nothing of the upstream projects but their credit
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotAboutTest {
    private static final String REPOSITORY = "https://github.com/evrenesat/u-tubot";
    private static final String SERVER = "https://utubot.example.com";

    private Context mContext;
    private ActivityController<FakeDialogView> mController;
    private FakeDialogView mView;

    /**
     * The dialog as the screen would get it: what it shows, per call. An activity, as a presenter only keeps a view of a live one.
     */
    public static final class FakeDialogView extends Activity implements AppDialogView {
        final List<List<OptionCategory>> shown = new ArrayList<>();
        final List<CharSequence> titles = new ArrayList<>();

        @Override
        public void show(List<OptionCategory> categories, CharSequence title, boolean isExpandable, boolean isTransparent, boolean isOverlay, int id) {
            shown.add(categories);
            titles.add(title);
        }

        List<OptionCategory> last() {
            return shown.get(shown.size() - 1);
        }

        @Override public void finish() { }
        @Override public void goBack() { }
        @Override public void clearBackstack() { }
        @Override public boolean canGoBack() { return false; }
        @Override public boolean isShown() { return true; }
        @Override public boolean isTransparent() { return false; }
        @Override public boolean isOverlay() { return false; }
        @Override public boolean isPaused() { return false; }
        @Override public int getViewId() { return 0; }
    }

    @Before
    public void setUp() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        mContext = RuntimeEnvironment.getApplication();
        mController = Robolectric.buildActivity(FakeDialogView.class).setup();
        mView = mController.get();
        AppDialogPresenter.instance(mView).setView(mView);
    }

    @After
    public void tearDown() {
        // The presenter is a singleton: it keeps no view of a destroyed screen
        if (mController != null) {
            mController.pause().stop().destroy();
        }
    }

    private List<OptionCategory> openAbout() {
        AboutSimpleSettingsPresenter.instance(mContext).show();

        return mView.last();
    }

    private static OptionItem rowOf(OptionCategory category) {
        return category.options.get(0);
    }

    private static String titleOf(OptionCategory category) {
        return String.valueOf(category.type == OptionCategory.TYPE_SINGLE_BUTTON ? rowOf(category).getTitle() : category.title);
    }

    private static OptionCategory find(List<OptionCategory> rows, String title) {
        for (OptionCategory category : rows) {
            if (title.equals(titleOf(category))) {
                return category;
            }
        }

        return null;
    }

    /**
     * The address a row's QR code panel shows
     */
    private String qrCodeOf(OptionCategory row) {
        int shownBefore = mView.shown.size();

        rowOf(row).onSelect(true);
        assertEquals("the row opens a panel", shownBefore + 1, mView.shown.size());
        OptionCategory panel = mView.last().get(0);
        assertEquals(OptionCategory.TYPE_QR_CODE, panel.type);

        return panel.qrCodeText;
    }

    @Test
    public void rows_areTheFlavorsOwn() {
        List<OptionCategory> rows = openAbout();
        List<String> titles = new ArrayList<>();

        for (OptionCategory row : rows) {
            titles.add(titleOf(row));
        }

        assertEquals("Donation is gone, the server is in", Arrays.asList("Server", "Feedback", "Releases", "Git repository",
                "Based on Electric Eel and SmartTube"), titles);
        assertEquals("u·tubot", mView.titles.get(0).toString().split(" ")[0]);
    }

    @Test
    public void everyRowsCodeIsOurTarget() {
        List<OptionCategory> rows = openAbout();

        assertEquals(REPOSITORY + "/issues", qrCodeOf(find(rows, "Feedback")));
        assertEquals(REPOSITORY + "/releases", qrCodeOf(find(rows, "Releases")));
        assertEquals(REPOSITORY, qrCodeOf(find(rows, "Git repository")));
        assertNull("no donation", find(rows, "Donation"));
    }

    @Test
    public void credit_isOneLineWithBothRepositories() {
        List<OptionCategory> rows = openAbout();
        OptionCategory credit = find(rows, "Based on Electric Eel and SmartTube");

        assertEquals(OptionCategory.TYPE_STRING_LIST, credit.type);
        assertEquals(2, credit.options.size());
        assertEquals("Electric Eel", credit.options.get(0).getTitle().toString());
        assertEquals("SmartTube", credit.options.get(1).getTitle().toString());

        int shownBefore = mView.shown.size();
        credit.options.get(0).onSelect(true);
        assertEquals("https://github.com/cygnusx-1-org/electriceel", mView.last().get(0).qrCodeText);
        credit.options.get(1).onSelect(true);
        assertEquals("https://github.com/yuliskov/SmartTube", mView.last().get(0).qrCodeText);
        assertEquals(shownBefore + 2, mView.shown.size());
    }

    @Test
    public void server_notSetUp() {
        UtubotSettings.instance(mContext).setUrl("");

        OptionItem server = rowOf(find(openAbout(), "Server"));

        assertEquals("Not set up", server.getDescription().toString());
    }

    @Test
    public void server_showsItsAddressAndACodeOfIt() {
        UtubotSettings.instance(mContext).setUrl(SERVER);

        OptionCategory server = find(openAbout(), "Server");

        assertEquals(SERVER, rowOf(server).getDescription().toString());
        assertEquals(SERVER, qrCodeOf(server));
        assertTrue(mView.titles.get(mView.titles.size() - 1).toString().contains("Server"));
    }
}
