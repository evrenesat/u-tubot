package com.liskovsoft.smartyoutubetv2.tv.ui.mod.leanback.misc;

import android.content.Context;
import android.graphics.Color;

import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutSeekBar;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.ConscryptMode;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

/**
 * What the seek bar actually accumulates: a new segment list replaces the rectangles of the old one, so taking a director's cut off
 * cannot leave its bright kept parts and dark hatched cut-outs underneath the sponsor colours.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
// The app's Conscrypt has no native library here, and no TLS is used
@ConscryptMode(ConscryptMode.Mode.OFF)
public class SeekBarSegmentsTest {
    private SeekBar mSeekBar;

    @Before
    public void setUp() {
        Context context = RuntimeEnvironment.getApplication();
        mSeekBar = new SeekBar(context, null);
    }

    @Test
    public void aNewList_replacesTheRectanglesOfTheCut() {
        mSeekBar.setSegments(Arrays.asList(segment(0.1f, 0.4f, UtubotCutSeekBar.KEPT_COLOR, false),
                segment(0.4f, 0.6f, UtubotCutSeekBar.CUT_COLOR, true)));
        assertEquals(2, rectangles().size());

        mSeekBar.setSegments(Arrays.asList(segment(0.7f, 0.8f, Color.GREEN, false)));

        List<?> rectangles = rectangles();
        assertEquals(1, rectangles.size());
        assertEquals(Color.GREEN, colorOf(rectangles.get(0)));
        assertFalse(hatchedOf(rectangles.get(0)));
    }

    @Test
    public void aNullList_clearsTheRectangles() {
        mSeekBar.setSegments(Arrays.asList(segment(0.1f, 0.4f, UtubotCutSeekBar.KEPT_COLOR, false)));

        mSeekBar.setSegments(null);

        assertEquals(0, rectangles().size());
    }

    private List<?> rectangles() {
        try {
            Field field = SeekBar.class.getDeclaredField("mSeekBarRectangles");
            field.setAccessible(true);
            return (List<?>) field.get(mSeekBar);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    private int colorOf(Object rectangle) {
        try {
            Field field = rectangle.getClass().getDeclaredField("paint");
            field.setAccessible(true);
            android.graphics.Paint paint = (android.graphics.Paint) field.get(rectangle);
            return paint.getColor();
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    private boolean hatchedOf(Object rectangle) {
        try {
            Field field = rectangle.getClass().getDeclaredField("hatched");
            field.setAccessible(true);
            return (boolean) field.get(rectangle);
        } catch (ReflectiveOperationException e) {
            throw new AssertionError(e);
        }
    }

    private static SeekBarSegment segment(float startProgress, float endProgress, int color, boolean hatched) {
        SeekBarSegment segment = new SeekBarSegment();
        segment.startProgress = startProgress;
        segment.endProgress = endProgress;
        segment.color = color;
        segment.hatched = hatched;
        return segment;
    }
}
