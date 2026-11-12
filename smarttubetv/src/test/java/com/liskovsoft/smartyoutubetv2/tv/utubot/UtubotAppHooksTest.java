package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.view.View;
import android.view.ViewGroup;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import org.junit.Assume;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The app-wide hooks: the badge on every screen, and what the hooks keep of the screens they watch
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 33, application = Application.class)
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotAppHooksTest {
    private static int badgesIn(Activity activity) {
        ViewGroup content = activity.findViewById(android.R.id.content);
        int count = 0;

        for (int i = 0; i < content.getChildCount(); i++) {
            if (content.getChildAt(i) instanceof UtubotBadgeController.UtubotBadgeView) {
                count++;
            }
        }

        return count;
    }

    @Test
    public void everyScreenGetsOneBadgeAndLosesItWithTheScreen() {
        Assume.assumeTrue(UtubotSettings.isBuiltIn());
        UtubotAppHooks.install(RuntimeEnvironment.getApplication());

        org.robolectric.android.controller.ActivityController<UtubotPanelControllerTest.ScreenActivity> controller =
                Robolectric.buildActivity(UtubotPanelControllerTest.ScreenActivity.class).setup();
        Activity activity = controller.get();

        assertEquals(1, badgesIn(activity));

        controller.pause().resume();
        assertEquals("resuming again doesn't add a second badge", 1, badgesIn(activity));

        controller.pause().stop().destroy();
        assertEquals(0, badgesIn(activity));
    }

    /**
     * The controllers are the values of a WeakHashMap keyed by their activity: a value that holds its key keeps the entry alive for
     * good. The activity and its views (which hold it as their context) may only be held weakly.
     */
    @Test
    public void theBadgeControllerHoldsNeitherItsActivityNorItsViewsStrongly() throws Exception {
        Activity activity = Robolectric.buildActivity(UtubotPanelControllerTest.ScreenActivity.class).setup().get();
        UtubotBadgeController controller = new UtubotBadgeController(activity);
        controller.onResume();

        assertHoldsNoActivityStrongly(controller);
        assertEquals(1, badgesIn(activity));

        controller.onDestroy();
        assertEquals(0, badgesIn(activity));
    }

    @Test
    public void aControllerWhoseActivityIsGoneDoesNothing() throws Exception {
        Activity activity = Robolectric.buildActivity(UtubotPanelControllerTest.ScreenActivity.class).setup().get();
        UtubotBadgeController controller = new UtubotBadgeController(activity);
        java.lang.ref.WeakReference<?> gone = new java.lang.ref.WeakReference<>(null);
        setField(controller, "mActivity", gone);

        controller.onResume();
        controller.onPause();
        controller.onDestroy();

        assertEquals(0, badgesIn(activity));
    }

    private static void assertHoldsNoActivityStrongly(Object owner) throws Exception {
        for (Class<?> type = owner.getClass(); type != null && type != Object.class; type = type.getSuperclass()) {
            for (Field field : type.getDeclaredFields()) {
                if (Modifier.isStatic(field.getModifiers()) || field.getType().isPrimitive()) {
                    continue;
                }

                field.setAccessible(true);
                Object value = field.get(owner);
                String where = type.getSimpleName() + "." + field.getName();

                assertFalse(where + " holds an activity or a context", value instanceof Context);
                assertFalse(where + " holds a view, which holds the activity as its context", value instanceof View);

                // A lambda or listener kept here must not capture one either
                if (value != null && (value.getClass().isSynthetic() || value.getClass().isAnonymousClass())) {
                    for (Field captured : value.getClass().getDeclaredFields()) {
                        captured.setAccessible(true);
                        Object inner = captured.get(value);

                        assertFalse(where + " captures an activity or a context", inner instanceof Context);
                        assertFalse(where + " captures a view", inner instanceof View);
                    }
                }
            }
        }
    }

    private static void setField(Object owner, String name, Object value) throws Exception {
        Field field = owner.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(owner, value);
    }

    @Test
    public void theHelperSeesAStrongHold() throws Exception {
        class Holder {
            final Context mContext = RuntimeEnvironment.getApplication();
        }

        try {
            assertHoldsNoActivityStrongly(new Holder());
        } catch (AssertionError expected) {
            assertTrue(expected.getMessage().contains("holds an activity or a context"));
            return;
        }

        throw new AssertionError("a Context field went unnoticed");
    }
}
