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
 * The user-facing Real-Debrid films entry (issue 248): the film screen opens when the addon address and the IMDb id are set, not behind the
 * developer toggle, and the token never rides the intent.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotFilmsPresenterTest {
    private Context mContext;
    private UtubotSettings mSettings;

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.getApplication();
        mSettings = UtubotSettings.instance(mContext);
    }

    @Test
    public void theIntentIsNullWithoutTheAddressOrTheId() {
        assertNull(UtubotFilmsPresenter.instance(mContext).filmsIntent());

        mSettings.setFilmsAddonUrl("https://addon.example/realdebrid={token}");
        assertNull(UtubotFilmsPresenter.instance(mContext).filmsIntent());

        mSettings.setFilmsImdbId("tt0944947");
        assertNotNull(UtubotFilmsPresenter.instance(mContext).filmsIntent());
    }

    @Test
    public void theIntentOpensWithoutTheDeveloperToggleAndCarriesTheSkips() {
        if (!UtubotSettings.isBuiltIn()) {
            return;
        }

        // The developer toggle is off: the user entry still opens the film screen.
        assertFalse(mSettings.isFilmsDeveloperEnabled());

        mSettings.setFilmsAddonUrl("https://addon.example/realdebrid={token}");
        mSettings.setFilmsImdbId(" tt0944947 ");
        mSettings.setFilmsSkips("30,90");
        Intent intent = UtubotFilmsPresenter.instance(mContext).filmsIntent();

        assertNotNull(intent);
        assertEquals(UtubotFilmsPresenter.FILMS_ACTIVITY, intent.getComponent().getClassName());
        assertEquals("tt0944947", intent.getStringExtra(UtubotFilmsPresenter.EXTRA_IMDB_ID));
        assertEquals("30,90", intent.getStringExtra(UtubotFilmsPresenter.EXTRA_SKIPS));
        assertFalse("the token never rides the intent", intent.getExtras().toString().contains("token"));
    }
}
