package com.liskovsoft.smartyoutubetv2.tv.ui.widgets.layout;

import android.content.Context;
import android.view.View;
import android.view.ViewGroup;

/**
 * The minimum size of a tap target on a touch screen (Android's 48 dp). The leanback screens are built for a
 * D-pad, so a row, a dialog button or a menu item can be smaller than a finger. On a large touch screen the
 * interactive views are grown to this size (see {@link #ensureMinSize(View)}).
 */
public final class TouchTargets {
    /**
     * The minimum tap target, in density-independent pixels.
     */
    public static final int MIN_TARGET_DP = 48;

    private TouchTargets() {
    }

    /**
     * @return the minimum tap target in actual pixels for the given density (mdpi = 1.0)
     */
    public static int minTargetPx(float density) {
        return (int) Math.round(MIN_TARGET_DP * density);
    }

    /**
     * @return the minimum tap target in actual pixels for the screen the context is on
     */
    public static int minTargetPx(Context context) {
        if (context == null || context.getResources() == null) {
            return MIN_TARGET_DP;
        }
        return minTargetPx(context.getResources().getDisplayMetrics().density);
    }

    /**
     * Grows the view's width and height to the minimum tap target when they are smaller. A view with a fixed size
     * of 0 (e.g. a content view that lets its child decide) is left alone: only a real, too-small size is grown.
     */
    public static void ensureMinSize(View view) {
        if (view == null) {
            return;
        }
        ViewGroup.LayoutParams params = view.getLayoutParams();
        if (params == null) {
            return;
        }
        int px = minTargetPx(view.getContext());
        boolean changed = false;
        if (params.width > 0 && params.width < px) {
            params.width = px;
            changed = true;
        }
        if (params.height > 0 && params.height < px) {
            params.height = px;
            changed = true;
        }
        if (changed) {
            view.setLayoutParams(params);
        }
    }
}
