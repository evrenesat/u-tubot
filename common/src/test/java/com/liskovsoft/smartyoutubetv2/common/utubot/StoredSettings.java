package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.SharedPreferences;

import org.robolectric.util.ReflectionHelpers;

/**
 * The stored values behind the settings singleton, for tests that start from what an earlier version left on the device. The singleton
 * itself stays: other parts of the layer keep a reference to it.
 */
public final class StoredSettings {
    private StoredSettings() {
    }

    public static SharedPreferences prefsOf(UtubotSettings settings) {
        return ReflectionHelpers.getField(settings, "mPrefs");
    }

    /**
     * Forgets everything stored, so reads fall back to their defaults
     */
    public static SharedPreferences.Editor cleared(UtubotSettings settings) {
        return prefsOf(settings).edit().clear();
    }
}
