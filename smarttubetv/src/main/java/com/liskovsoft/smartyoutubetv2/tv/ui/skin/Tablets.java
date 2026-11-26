package com.liskovsoft.smartyoutubetv2.tv.ui.skin;

import android.content.res.Configuration;
import android.content.Context;

/**
 * A large touch screen: a tablet or a big phone (at least "large", with a touchscreen). The leanback layout is built for a TV reached
 * with a remote, so on such a device the app shows the modern, touch-friendly screens instead of it (see SkinRegistry). A TV has no
 * touchscreen the navigation can rely on; a phone is not large.
 */
public final class Tablets {
    private Tablets() {
    }

    public static boolean isLargeTouchScreen(Context context) {
        return isLargeTouchScreen(context.getResources().getConfiguration());
    }

    public static boolean isLargeTouchScreen(Configuration config) {
        boolean large = (config.screenLayout & Configuration.SCREENLAYOUT_SIZE_MASK) >= Configuration.SCREENLAYOUT_SIZE_LARGE;
        // A value of notouch (0) means no touchscreen the navigation can use; anything else (finger, stylus) is a touch screen.
        boolean touch = config.touchscreen != Configuration.TOUCHSCREEN_NOTOUCH;

        return large && touch;
    }
}
