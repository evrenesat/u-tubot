package com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui;

import android.graphics.Color;

public class SeekBarSegment {
    public float startProgress;
    public float endProgress;
    public int color = Color.GREEN;
    /** A diagonal pattern over the colour, so a cut-out range is not mistaken for a kept one */
    public boolean hatched;
}
