package com.liskovsoft.smartyoutubetv2.tv.ui.skin;

import android.content.res.Configuration;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static android.content.res.Configuration.SCREENLAYOUT_SIZE_LARGE;
import static android.content.res.Configuration.SCREENLAYOUT_SIZE_NORMAL;
import static android.content.res.Configuration.SCREENLAYOUT_SIZE_XLARGE;
import static android.content.res.Configuration.TOUCHSCREEN_NOTOUCH;
import static android.content.res.Configuration.TOUCHSCREEN_FINGER;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class TabletsTest {
    @Test
    public void aNormalTouchScreenIsNotALargeTouchScreen() {
        assertFalse(Tablets.isLargeTouchScreen(screen(SCREENLAYOUT_SIZE_NORMAL, TOUCHSCREEN_FINGER)));
    }

    @Test
    public void aLargeScreenWithoutTouchIsNotALargeTouchScreen() {
        assertFalse(Tablets.isLargeTouchScreen(screen(SCREENLAYOUT_SIZE_LARGE, TOUCHSCREEN_NOTOUCH)));
    }

    @Test
    public void aLargeTouchScreenIsDetected() {
        assertTrue(Tablets.isLargeTouchScreen(screen(SCREENLAYOUT_SIZE_LARGE, TOUCHSCREEN_FINGER)));
    }

    @Test
    public void anXLargeTouchScreenIsDetected() {
        assertTrue(Tablets.isLargeTouchScreen(screen(SCREENLAYOUT_SIZE_XLARGE, TOUCHSCREEN_FINGER)));
    }

    private static Configuration screen(int screenLayout, int touchscreen) {
        Configuration config = new Configuration();
        config.screenLayout = screenLayout;
        config.touchscreen = touchscreen;
        return config;
    }
}
