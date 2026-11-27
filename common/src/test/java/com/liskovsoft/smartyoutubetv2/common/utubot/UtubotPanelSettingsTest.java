package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.SystemGeneralSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCaptionStore.Usage;

import org.junit.Assume;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotPanelSettingsTest {
    private Activity mActivity;
    private UtubotSettings mSettings;

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mSettings = UtubotSettings.instance(mActivity);
        StoredSettings.cleared(mSettings).commit();
    }

    @Test
    public void thePanelWaitsOneAndAHalfSecondsLongerThanBeforeByDefault() {
        assertEquals(1800, UtubotSettings.DEFAULT_PANEL_DELAY_MS);
        assertEquals(1800, mSettings.getPanelDelayMs());
    }

    @Test
    public void theChoicesAreOneOnePointEightThreeAndFiveSeconds() {
        assertEquals(4, UtubotSettings.PANEL_DELAY_CHOICES_MS.length);
        assertEquals(1000, UtubotSettings.PANEL_DELAY_CHOICES_MS[0]);
        assertEquals(1800, UtubotSettings.PANEL_DELAY_CHOICES_MS[1]);
        assertEquals(3000, UtubotSettings.PANEL_DELAY_CHOICES_MS[2]);
        assertEquals(5000, UtubotSettings.PANEL_DELAY_CHOICES_MS[3]);
    }

    @Test
    public void aChosenDelayIsKept() {
        for (int delayMs : UtubotSettings.PANEL_DELAY_CHOICES_MS) {
            mSettings.setPanelDelayMs(delayMs);

            assertEquals(delayMs, mSettings.getPanelDelayMs());
        }
    }

    @Test
    public void anyValueInRangeIsKeptAndOneOutsideChangesNothing() {
        mSettings.setPanelDelayMs(3000);
        mSettings.setPanelDelayMs(700);

        assertEquals(700, mSettings.getPanelDelayMs());

        mSettings.setPanelDelayMs(0);
        assertEquals(0, mSettings.getPanelDelayMs());

        mSettings.setPanelDelayMs(10_001);
        mSettings.setPanelDelayMs(-5);
        assertEquals(0, mSettings.getPanelDelayMs());

        StoredSettings.prefsOf(mSettings).edit().putInt("panel_delay_ms", 99_999).commit();
        assertEquals(1800, mSettings.getPanelDelayMs());
    }

    @Test
    public void aDelayThatIsNoChoiceReadsAsCustom() {
        assertEquals("Custom (700 ms)", UtubotSettingsPresenter.formatDelay(mActivity, 700));
    }

    @Test
    public void delaysReadAsSeconds() {
        assertEquals("1 s", UtubotSettingsPresenter.formatDelay(mActivity, 1000));
        assertEquals("1.8 s", UtubotSettingsPresenter.formatDelay(mActivity, 1800));
        assertEquals("3 s", UtubotSettingsPresenter.formatDelay(mActivity, 3000));
        assertEquals("5 s", UtubotSettingsPresenter.formatDelay(mActivity, 5000));
    }

    @Test
    public void theBrowseRefreshStartsAtTenMinutesWithFiveChoices() {
        assertEquals(BrowseCachePolicy.DEFAULT_REFRESH_MINUTES, mSettings.getBrowseRefreshMinutes());
        assertEquals(5, BrowseCachePolicy.REFRESH_MINUTES_CHOICES.length);
    }

    @Test
    public void aChosenBrowseRefreshIsKept() {
        for (int minutes : BrowseCachePolicy.REFRESH_MINUTES_CHOICES) {
            mSettings.setBrowseRefreshMinutes(minutes);

            assertEquals(minutes, mSettings.getBrowseRefreshMinutes());
        }

        mSettings.setBrowseRefreshMinutes(15);
        assertEquals(60, mSettings.getBrowseRefreshMinutes());
    }

    @Test
    public void browseRefreshReadsAsMinutes() {
        assertEquals("10 min", UtubotSettings.formatBrowseRefresh(mActivity, 10));
        assertEquals("30 min", UtubotSettings.formatBrowseRefresh(mActivity, 30));
    }

    @Test
    public void theSettingsListShowsTheReadingPaceAfterTheSummaryDelay() {
        OptionCategory reading = UtubotSettingsPresenter.instance(mActivity).buildCategories().get(5);

        assertEquals(mActivity.getString(R.string.utubot_auto_scroll), reading.options.get(0).getTitle().toString());
        assertEquals("45 px/s", reading.options.get(0).getDescription().toString());
    }

    @Test
    public void theSettingsListShowsTheCurrentDelayRightAfterTheSummaryPanel() {
        mSettings.setPanelDelayMs(3000);

        OptionCategory delay = UtubotSettingsPresenter.instance(mActivity).buildCategories().get(4);

        assertEquals(mActivity.getString(R.string.utubot_panel_delay), delay.options.get(0).getTitle().toString());
        assertEquals("3 s", delay.options.get(0).getDescription().toString());
    }

    @Test
    public void captionStorageShowsSizeVideosAndTracks() {
        String text = UtubotSettingsPresenter.formatCaptionStorage(mActivity, new Usage(2, 3, 13L * 1024 * 1024));

        assertTrue(text.contains("13.0 MB"));
        assertTrue(text.contains("2 videos"));
        assertTrue(text.contains("3 tracks"));
        assertFalse(text.contains("Caption storage is large"));
    }

    @Test
    public void captionStorageWarnsAtTheThreshold() {
        String text = UtubotSettingsPresenter.formatCaptionStorage(mActivity,
                new Usage(10, 20, UtubotCaptionStore.WARN_BYTES));

        assertEquals(mActivity.getString(R.string.utubot_caption_storage_warning,
                UtubotSettingsPresenter.formatBytes(UtubotCaptionStore.WARN_BYTES)), text.substring(text.indexOf('\n') + 1));
    }

    @Test
    public void anEmptyCaptionStoreSaysSo() {
        assertEquals(mActivity.getString(R.string.utubot_caption_storage_empty),
                UtubotSettingsPresenter.formatCaptionStorage(mActivity, new Usage(0, 0, 0)));
    }

    @Test
    public void updateChecksRunEveryFiveMinutesByDefaultAndOnlyChosenIntervalsAreKept() {
        assertEquals(5, mSettings.getUpdateIntervalMinutes());

        mSettings.setUpdateIntervalMinutes(60);
        assertEquals(60, mSettings.getUpdateIntervalMinutes());

        mSettings.setUpdateIntervalMinutes(7);
        assertEquals(60, mSettings.getUpdateIntervalMinutes());
    }

    @Test
    public void developmentModeIsOnByDefaultForTheBuiltInFlavor() {
        assertEquals(UtubotSettings.isBuiltIn(), mSettings.isDevelopmentMode());

        mSettings.setDevelopmentMode(false);
        assertEquals(false, mSettings.isDevelopmentMode());
    }

    @Test
    public void theBrowseRefreshCardIsInTheSystemGeneral() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        List<SettingsItem> items = SystemGeneralSettingsPresenter.instance(mActivity).getItems(mActivity);

        assertEquals(mActivity.getString(R.string.category_background_playback), items.get(1).title.toString());
        assertEquals(mActivity.getString(R.string.utubot_browse_refresh), items.get(2).title.toString());
        assertEquals(mActivity.getString(R.string.child_mode), items.get(3).title.toString());
        assertEquals(R.drawable.settings_home_rows, items.get(2).imageResId);
    }
}
