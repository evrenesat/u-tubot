package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;

/**
 * The Real-Debrid films developer entry: off by default, and its only row is the hand-written skip list (issue 211). The addon address, the token
 * and the IMDb id are in the user-facing "Films" entry (issue 248).
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmsDeveloperPresenterTest {
    private Context mContext;
    private UtubotSettings mSettings;

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.getApplication();
        mSettings = UtubotSettings.instance(mContext);
    }

    @Test
    public void theDeveloperEntryShowsTheSkipList() {
        mSettings.setFilmsSkips("30,90;600,720");

        // Opening the entry does not crash and the skip list round-trips through the private prefs.
        UtubotFilmsDeveloperPresenter.instance(mContext).show();
        assertEquals("30,90;600,720", mSettings.getFilmsSkips());

        mSettings.setFilmsSkips("");
        UtubotFilmsDeveloperPresenter.instance(mContext).show();
        assertEquals("", mSettings.getFilmsSkips());
    }
}
