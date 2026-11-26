package com.liskovsoft.smartyoutubetv2.tv.ui.widgets.layout;

import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import static org.junit.Assert.assertEquals;

/**
 * The dp conversions are pure; {@link #ensureMinSize(View)} needs a view with a screen, hence Robolectric.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = android.app.Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class TouchTargetsTest {
    @Test
    public void targetAtEachDensity() {
        assertEquals(48, TouchTargets.minTargetPx(1.0f));      // mdpi
        assertEquals(72, TouchTargets.minTargetPx(1.5f));      // hdpi-ish (a 240 dpi tablet)
        assertEquals(96, TouchTargets.minTargetPx(2.0f));      // xhdpi
        assertEquals(120, TouchTargets.minTargetPx(2.5f));     // xxhdpi
    }

    @Test
    public void rounds_to_nearest_pixel() {
        // 48 * 1.25 = 60 exactly, 48 * 1.1 = 52.8 -> 53
        assertEquals(60, TouchTargets.minTargetPx(1.25f));
        assertEquals(53, TouchTargets.minTargetPx(1.1f));
    }

    private static LinearLayout row(int width, int height) {
        return new LinearLayout(RuntimeEnvironment.getApplication(), null) {{
            this.setLayoutParams(new ViewGroup.LayoutParams(width, height));
        }};
    }

    @Test
    public void grows_a_too_small_row() {
        // A 240 dpi screen: the 48 dp target is 72 px.
        int target = TouchTargets.minTargetPx(RuntimeEnvironment.getApplication().getResources().getDisplayMetrics().density);

        LinearLayout row = row(40, 40);
        TouchTargets.ensureMinSize(row);

        assertEquals(target, row.getLayoutParams().width);
        assertEquals(target, row.getLayoutParams().height);
    }

    @Test
    public void leaves_a_big_enough_row_alone() {
        LinearLayout row = row(200, 200);
        TouchTargets.ensureMinSize(row);

        assertEquals(200, row.getLayoutParams().width);
        assertEquals(200, row.getLayoutParams().height);
    }

    @Test
    public void a_zero_or_missing_size_is_not_grown() {
        // 0 means "let the child decide", not a too-small target; 100 px is already above the target.
        LinearLayout row = row(0, 100);
        TouchTargets.ensureMinSize(row);

        assertEquals(0, row.getLayoutParams().width);
        assertEquals(100, row.getLayoutParams().height);

        TouchTargets.ensureMinSize(new View(RuntimeEnvironment.getApplication()));
    }
}
