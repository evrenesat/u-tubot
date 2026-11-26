package com.liskovsoft.smartyoutubetv2.tv.ui.skin;

import android.app.Application;
import android.content.Context;
import android.content.res.Configuration;

import com.liskovsoft.smartyoutubetv2.common.app.views.BrowseView;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.app.views.ViewManager;
import com.liskovsoft.smartyoutubetv2.common.misc.Skins;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.tv.ui.browse.BrowseActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.modern.browse.ModernBrowseActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.playback.PlaybackActivity;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;
import org.robolectric.shadows.ShadowLooper;

import java.util.Arrays;

import static org.junit.Assert.assertEquals;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class TabletSkinTest {
    private SkinRegistry mRegistry;

    @Before
    public void setUp() {
        mRegistry = new SkinRegistry(Arrays.asList(new ClassicSkin(), new ModernSkin()));
        mRegistry.setClassicRoot(BrowseActivity.class);
        mRegistry.addView(BrowseView.class, BrowseActivity.class, true);
        mRegistry.addView(PlaybackView.class, PlaybackActivity.class, false);
    }

    @After
    public void tearDown() {
        MainUIData.instance(getContext()).setSkinId(MainUIData.SKIN_CLASSIC);
        Skins.setProvider(null);
    }

    @Test
    public void theClassicLayoutIsReplacedByTheModernOneOnALargeTouchScreen() {
        largeTouchScreen();
        pick(MainUIData.SKIN_CLASSIC);
        mRegistry.init(getContext());

        assertEquals(MainUIData.SKIN_MODERN, Skins.getAppliedSkinId());
        assertEquals(ModernBrowseActivity.class, getViewManager().getRootActivity());
        assertEquals(ModernBrowseActivity.class, getViewManager().getActivity(BrowseView.class));
    }

    @Test
    public void aTouchSkinIsKeptOnALargeTouchScreen() {
        largeTouchScreen();
        pick(MainUIData.SKIN_MODERN);
        mRegistry.init(getContext());

        assertEquals(MainUIData.SKIN_MODERN, Skins.getAppliedSkinId());
        assertEquals(ModernBrowseActivity.class, getViewManager().getRootActivity());
    }

    @Test
    public void pickingClassicLaterStaysModernOnALargeTouchScreen() {
        largeTouchScreen();
        pick(MainUIData.SKIN_MODERN);
        mRegistry.init(getContext());
        pick(MainUIData.SKIN_CLASSIC);
        Skins.applyPickedSkin(getContext());

        // The classic layout is never applied on a tablet: the choice is kept, the screen stays modern.
        assertEquals(MainUIData.SKIN_MODERN, Skins.getAppliedSkinId());
    }

    @Test
    public void theClassicLayoutStaysOnANormalTouchScreen() {
        normalTouchScreen();
        pick(MainUIData.SKIN_CLASSIC);
        mRegistry.init(getContext());

        assertEquals(MainUIData.SKIN_CLASSIC, Skins.getAppliedSkinId());
        assertEquals(BrowseActivity.class, getViewManager().getRootActivity());
    }

    private static void largeTouchScreen() {
        setScreen(Configuration.SCREENLAYOUT_SIZE_LARGE, Configuration.TOUCHSCREEN_FINGER);
    }

    private static void normalTouchScreen() {
        setScreen(Configuration.SCREENLAYOUT_SIZE_NORMAL, Configuration.TOUCHSCREEN_FINGER);
    }

    private static void setScreen(int screenLayout, int touchscreen) {
        Configuration config = getContext().getResources().getConfiguration();
        config.screenLayout = screenLayout;
        config.touchscreen = touchscreen;
    }

    private static void pick(int skinId) {
        MainUIData.instance(getContext()).setSkinId(skinId);
        ShadowLooper.shadowMainLooper().idle();
    }

    private static Context getContext() {
        return RuntimeEnvironment.getApplication();
    }

    private static ViewManager getViewManager() {
        return ViewManager.instance(getContext());
    }
}
