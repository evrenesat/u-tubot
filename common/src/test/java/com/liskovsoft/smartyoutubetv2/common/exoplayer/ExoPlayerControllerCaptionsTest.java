package com.liskovsoft.smartyoutubetv2.common.exoplayer;

import com.google.android.exoplayer2.source.MediaSource;
import com.google.android.exoplayer2.source.SilenceMediaSource;
import com.google.android.exoplayer2.source.sabr.ValidatedNetwork;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.controller.ExoPlayerController;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;

import java.lang.reflect.Proxy;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * What the player remembers of the source it opened for the HQ captions belongs to the video it opened it for: the captions of the next
 * video are never merged into it.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class ExoPlayerControllerCaptionsTest {
    private static final String VIDEO_A = "Lqig_Ui9Hh0";
    private static final String VIDEO_B = "jNQXAC9IVRw";
    private final MediaSource mBase = new SilenceMediaSource(1_000_000);
    private ExoPlayerController mController;
    private Video mVideoA;

    @Before
    public void setUp() {
        PlayerEventListener listener = (PlayerEventListener) Proxy.newProxyInstance(PlayerEventListener.class.getClassLoader(),
                new Class<?>[]{PlayerEventListener.class}, (proxy, method, args) -> method.getReturnType() == boolean.class ? false : null);
        mController = new ExoPlayerController(RuntimeEnvironment.getApplication(), listener);
        mVideoA = video(VIDEO_A);
        mController.setVideo(mVideoA);
        openedWith(mBase, true, true);
    }

    @After
    public void tearDown() {
        // The controller installs the network check of the player for the whole process
        ValidatedNetwork.setSupplier(null);
    }

    @Test
    public void anotherVideo_dropsTheSourceOfThePreviousOne() {
        mController.setVideo(video(VIDEO_B));

        assertNull(base());
        assertFalse(attached());
        assertFalse(selectPending());
    }

    @Test
    public void noVideo_dropsTheSource() {
        mController.setVideo(null);

        assertNull(base());
        assertFalse(attached());
    }

    @Test
    public void theSameVideoAgain_keepsTheSource() {
        mController.setVideo(video(VIDEO_A));

        assertSame(mBase, base());
        assertTrue(attached());
        assertTrue(selectPending());
    }

    @Test
    public void theSameVideoObjectAgain_keepsTheSource() {
        mController.setVideo(mVideoA);

        assertSame(mBase, base());
        assertTrue(attached());
    }

    private void openedWith(MediaSource base, boolean attached, boolean selectPending) {
        ReflectionHelpers.setField(mController, "mUtubotBaseSource", base);
        ReflectionHelpers.setField(mController, "mUtubotCaptionsAttached", attached);
        ReflectionHelpers.setField(mController, "mUtubotCaptionsSelectPending", selectPending);
    }

    private MediaSource base() {
        return ReflectionHelpers.getField(mController, "mUtubotBaseSource");
    }

    private boolean attached() {
        return ReflectionHelpers.getField(mController, "mUtubotCaptionsAttached");
    }

    private boolean selectPending() {
        return ReflectionHelpers.getField(mController, "mUtubotCaptionsSelectPending");
    }

    private static Video video(String videoId) {
        Video video = new Video();
        video.videoId = videoId;

        return video;
    }
}
