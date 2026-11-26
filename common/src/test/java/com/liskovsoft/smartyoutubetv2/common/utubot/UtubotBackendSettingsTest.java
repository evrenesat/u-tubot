package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotBackendSettingsPresenter;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotBackendSettingsTest {
    private Activity mActivity;

    @Before
    public void setUp() {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
    }

    @Test
    public void settingsList_hasImportPairTestConnectionWebAdminAdvanced() {
        List<OptionCategory> categories = UtubotBackendSettingsPresenter.instance(mActivity).buildCategories();
        List<String> titles = new ArrayList<>();
        List<Integer> types = new ArrayList<>();

        for (OptionCategory category : categories) {
            titles.add(category.options.get(0).getTitle().toString());
            types.add(category.type);
        }

        assertEquals(Arrays.asList(
                mActivity.getString(R.string.utubot_import_setup),
                mActivity.getString(R.string.utubot_pair),
                mActivity.getString(R.string.utubot_test_connection),
                mActivity.getString(R.string.utubot_web_admin),
                mActivity.getString(R.string.utubot_advanced)), titles);
        for (int type : types) {
            assertEquals(OptionCategory.TYPE_SINGLE_BUTTON, type);
        }
    }
}
