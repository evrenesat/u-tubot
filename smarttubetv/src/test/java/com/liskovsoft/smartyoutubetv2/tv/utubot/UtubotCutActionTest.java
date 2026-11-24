package com.liskovsoft.smartyoutubetv2.tv.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The player's cut button is only there for the built-in flavor pointed at a backend
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
// The app's Conscrypt has no native library here, and no TLS is used
@ConscryptMode(ConscryptMode.Mode.OFF)
public class UtubotCutActionTest {
    private UtubotSettings mSettings;

    @Before
    public void setUp() {
        mSettings = UtubotSettings.instance(RuntimeEnvironment.getApplication());
        mSettings.setUrl("http://127.0.0.1:9");
    }

    @After
    public void tearDown() {
        mSettings.setUrl("");
    }

    @Test
    public void isAvailable_withTheFlavorAndABackend() {
        assertTrue(UtubotCutAction.isAvailable(RuntimeEnvironment.getApplication()));
    }

    @Test
    public void isNotAvailable_withoutABackend() {
        mSettings.setUrl("");

        assertFalse(UtubotCutAction.isAvailable(RuntimeEnvironment.getApplication()));
    }
}
