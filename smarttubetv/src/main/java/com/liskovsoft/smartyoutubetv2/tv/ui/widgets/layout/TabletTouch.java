package com.liskovsoft.smartyoutubetv2.tv.ui.widgets.layout;

import android.content.Context;
import android.content.res.Configuration;
import android.content.res.Resources;

/**
 * Decides whether the device is a large touch screen (a tablet, like the 10-inch 1920x1200 / 1200x1920
 * ones the issue checks), so the browse, the player, the settings and the dialogs can show a touch layout
 * that shares the TV code paths instead of the D-pad only one.
 */
public final class TabletTouch {
    /**
     * A diagonal at or above this many inches counts as a tablet. Below it the device is a phone.
     */
    public static final double TABLET_MIN_DIAGONAL_INCHES = 7.0;

    private TabletTouch() {
    }

    /**
     * @return true when the configuration reports a touch screen (not {@link Configuration#TOUCHSCREEN_NOTOUCH})
     */
    public static boolean isTouchDevice(Configuration configuration) {
        return configuration.touchscreen != Configuration.TOUCHSCREEN_NOTOUCH;
    }

    /**
     * The screen diagonal in inches from the pixels of one side and the density (dpi). The orientation does not
     * matter: the hypotenuse is the same in portrait and in landscape.
     */
    public static double diagonalInches(float widthPx, float heightPx, int densityDpi) {
        if (densityDpi <= 0) {
            return 0.0;
        }
        return Math.hypot(widthPx, heightPx) / densityDpi;
    }

    /**
     * @return true when the screen is both touch and large enough to be a tablet
     */
    public static boolean isLargeTouchScreen(Configuration configuration, float widthPx, float heightPx, int densityDpi) {
        return isTouchDevice(configuration) && diagonalInches(widthPx, heightPx, densityDpi) >= TABLET_MIN_DIAGONAL_INCHES;
    }

    /**
     * Convenience for a screen: the current configuration, the pixels of the current orientation and the density.
     */
    public static boolean isLargeTouchScreen(Context context) {
        if (context == null) {
            return false;
        }
        Resources resources = context.getResources();
        if (resources == null) {
            return false;
        }
        Configuration configuration = resources.getConfiguration();
        android.util.DisplayMetrics metrics = resources.getDisplayMetrics();
        return isLargeTouchScreen(configuration, metrics.widthPixels, metrics.heightPixels, metrics.densityDpi);
    }
}
