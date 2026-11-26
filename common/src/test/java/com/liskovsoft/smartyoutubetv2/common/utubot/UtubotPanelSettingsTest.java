package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;

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
    public void aValueThatIsNoChoiceChangesNothing() {
        mSettings.setPanelDelayMs(3000);
        mSettings.setPanelDelayMs(700);
        mSettings.setPanelDelayMs(0);

        assertEquals(3000, mSettings.getPanelDelayMs());

        StoredSettings.prefsOf(mSettings).edit().putInt("panel_delay_ms", 700).commit();
        assertEquals(1800, mSettings.getPanelDelayMs());
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
        assertEquals("10 min", UtubotSettingsPresenter.formatBrowseRefresh(mActivity, 10));
        assertEquals("30 min", UtubotSettingsPresenter.formatBrowseRefresh(mActivity, 30));
    }

    @Test
    public void theSettingsListShowsBrowseRefreshAfterTheSummaryDelay() {
        OptionCategory refresh = UtubotSettingsPresenter.instance(mActivity).buildCategories().get(7);

        assertEquals(mActivity.getString(R.string.utubot_browse_refresh), refresh.options.get(0).getTitle().toString());
        assertEquals("10 min", refresh.options.get(0).getDescription().toString());
    }

    @Test
    public void theSettingsListShowsTheCurrentDelayRightAfterTheSummaryPanel() {
        mSettings.setPanelDelayMs(3000);

        OptionCategory delay = UtubotSettingsPresenter.instance(mActivity).buildCategories().get(6);

        assertEquals(mActivity.getString(R.string.utubot_panel_delay), delay.options.get(0).getTitle().toString());
        assertEquals("3 s", delay.options.get(0).getDescription().toString());
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
}
