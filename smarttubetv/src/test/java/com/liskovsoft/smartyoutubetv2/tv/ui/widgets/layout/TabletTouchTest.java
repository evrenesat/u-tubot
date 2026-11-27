package com.liskovsoft.smartyoutubetv2.tv.ui.widgets.layout;

import android.content.res.Configuration;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class TabletTouchTest {
    // A 10-inch tablet: 1920x1200 at 240 dpi (2.5" x 1.5" per 100 dp, diagonal ~9.4")
    private static final int TABLET_DPI = 240;
    private static final float TABLET_W = 1920;
    private static final float TABLET_H = 1200;

    private static Configuration touch() {
        Configuration configuration = new Configuration();
        // TOUCHSCREEN_TOUCH was removed from the android-37 stub (the canonical check is != TOUCHSCREEN_NOTOUCH);
        // FINGER is a real touch value and satisfies the same test in TabletTouch.
        configuration.touchscreen = Configuration.TOUCHSCREEN_FINGER;
        return configuration;
    }

    private static Configuration noTouch() {
        Configuration configuration = new Configuration();
        configuration.touchscreen = Configuration.TOUCHSCREEN_NOTOUCH;
        return configuration;
    }

    @Test
    public void diagonal_of_a_10inch_tablet_is_about_nine_four() {
        // 1920x1200 @ 240 dpi -> hypot(1920,1200)/240 ~= 9.43
        double diagonal = TabletTouch.diagonalInches(TABLET_W, TABLET_H, TABLET_DPI);
        assertEquals(9.4f, diagonal, 0.1);
    }

    @Test
    public void diagonal_is_orientation_independent() {
        // Portrait 1200x1920 is the same tablet, the hypotenuse is unchanged
        double landscape = TabletTouch.diagonalInches(TABLET_W, TABLET_H, TABLET_DPI);
        double portrait = TabletTouch.diagonalInches(TABLET_H, TABLET_W, TABLET_DPI);
        assertEquals(landscape, portrait, 0.0001);
    }

    @Test
    public void a_10inch_tablet_with_touch_is_large() {
        assertTrue(TabletTouch.isLargeTouchScreen(touch(), TABLET_W, TABLET_H, TABLET_DPI));
    }

    @Test
    public void a_phone_is_not_large() {
        // A 6-inch phone: 1080x2400 @ 480 dpi -> hypot/480 ~= 5.66
        double diagonal = TabletTouch.diagonalInches(1080f, 2400f, 480);
        assertTrue(6.0 > diagonal && diagonal > 5.0);
        assertFalse(TabletTouch.isLargeTouchScreen(touch(), 1080f, 2400f, 480));
    }

    @Test
    public void touch_is_required() {
        // A large screen without a touch screen (a TV) is not a large touch screen
        assertFalse(TabletTouch.isLargeTouchScreen(noTouch(), TABLET_W, TABLET_H, TABLET_DPI));
    }

    @Test
    public void a_small_touch_screen_is_not_large() {
        // A 5-inch phone with touch
        assertFalse(TabletTouch.isLargeTouchScreen(touch(), 720f, 1280f, 320));
    }

    @Test
    public void bad_density_returns_false() {
        assertFalse(TabletTouch.isLargeTouchScreen(touch(), TABLET_W, TABLET_H, 0));
    }
}
