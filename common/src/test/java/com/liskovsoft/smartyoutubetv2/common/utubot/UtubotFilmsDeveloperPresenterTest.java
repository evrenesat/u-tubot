package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.Intent;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

/**
 * The Real-Debrid films developer entry: off by default, and the film screen opens only with the entry on and an address and an IMDb id set.
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
    public void theEntryIsOffByDefault() {
        assertFalse(mSettings.isFilmsDeveloperEnabled());
        assertNull(UtubotFilmsDeveloperPresenter.instance(mContext).filmsIntent());
    }

    @Test
    public void theIntentNeedsTheEntryAnAddressAndAnId() {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        mSettings.setFilmsDeveloperEnabled(true);
        assertNull(UtubotFilmsDeveloperPresenter.instance(mContext).filmsIntent());

        mSettings.setFilmsAddonUrl("https://addon.example/realdebrid={token}");
        mSettings.setFilmsImdbId(" tt0944947 ");
        mSettings.setFilmsSkips("30,90");
        Intent intent = UtubotFilmsDeveloperPresenter.instance(mContext).filmsIntent();

        assertNotNull(intent);
        assertEquals(UtubotFilmsDeveloperPresenter.FILMS_ACTIVITY, intent.getComponent().getClassName());
        assertEquals("tt0944947", intent.getStringExtra(UtubotFilmsDeveloperPresenter.EXTRA_ID));
        assertEquals("movie", intent.getStringExtra(UtubotFilmsDeveloperPresenter.EXTRA_TYPE));
        assertFalse("the token never rides the intent", intent.getExtras().toString().contains("token"));

        mSettings.setFilmsDeveloperEnabled(false);
        assertNull(UtubotFilmsDeveloperPresenter.instance(mContext).filmsIntent());
    }
}
