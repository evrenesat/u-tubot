package com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.ExoFormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.TrackSelectorManager;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * The subtitle choice saved in the settings is applied when a video loads (twice: with the source and with the metadata). It is usually
 * "no subtitles", and must not take the HQ captions of u·tubot away once they are selected for the video.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCaptionsRestoreTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String OTHER_VIDEO = "jNQXAC9IVRw";

    @Before
    public void setUp() {
        reset();
    }

    @After
    public void tearDown() {
        reset();
        Utils.sHandler.removeCallbacksAndMessages(null);
    }

    @Test
    public void hqCaptionsSelectedForTheVideo_stayWhenTheSavedChoiceIsNoSubtitles() {
        getPlayerData().setFormat(FormatItem.SUBTITLE_NONE);
        TestStateController controller = new TestStateController(VIDEO, hq(VIDEO, "tr"));

        controller.onSourceChanged(controller.getVideo());

        assertTrue(controller.subtitlesSet.isEmpty());
    }

    @Test
    public void hqCaptionsSelectedForTheVideo_stayWhenTheSavedChoiceIsAnotherLanguage() {
        getPlayerData().setFormat(FormatItem.fromLanguage("en"));
        TestStateController controller = new TestStateController(VIDEO, hq(VIDEO, "tr"));

        controller.onSourceChanged(controller.getVideo());

        assertTrue(controller.subtitlesSet.isEmpty());
    }

    @Test
    public void hqCaptionsOfThePreviousVideo_giveWayToTheSavedChoice() {
        getPlayerData().setFormat(FormatItem.SUBTITLE_NONE);
        TestStateController controller = new TestStateController(VIDEO, hq(OTHER_VIDEO, "tr"));

        controller.onSourceChanged(controller.getVideo());

        assertEquals(1, controller.subtitlesSet.size());
        assertSame(getPlayerData().getFormat(FormatItem.TYPE_SUBTITLE), controller.subtitlesSet.get(0));
    }

    @Test
    public void otherSelectedSubtitles_giveWayToTheSavedChoice() {
        getPlayerData().setFormat(FormatItem.SUBTITLE_NONE);
        TestStateController controller = new TestStateController(VIDEO, FormatItem.fromLanguage("en"));

        controller.onSourceChanged(controller.getVideo());

        assertEquals(1, controller.subtitlesSet.size());
    }

    @Test
    public void nothingSelected_appliesTheSavedChoice() {
        getPlayerData().setFormat(FormatItem.SUBTITLE_NONE);
        TestStateController controller = new TestStateController(VIDEO, null);

        controller.onSourceChanged(controller.getVideo());

        assertEquals(1, controller.subtitlesSet.size());
    }

    private static FormatItem hq(String videoId, String language) {
        return ExoFormatItem.from(FormatItem.TYPE_SUBTITLE, TrackSelectorManager.RENDERER_INDEX_SUBTITLE, "utubot:" + videoId + ":" + language,
                null, -1, -1, -1, language, false, -1, false, false);
    }

    private static PlayerData getPlayerData() {
        return PlayerData.instance(RuntimeEnvironment.getApplication());
    }

    private static void reset() {
        getPlayerData().setFormat(FormatItem.SUBTITLE_NONE);
    }

    private static class TestStateController extends VideoStateController {
        private final Video mVideo = new Video();
        private final List<FormatItem> subtitlesSet = new ArrayList<>();
        private final PlaybackView mPlayer;

        private TestStateController(String videoId, FormatItem selectedSubtitle) {
            mVideo.videoId = videoId;
            setAltContext(RuntimeEnvironment.getApplication());
            mPlayer = (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                    (proxy, method, args) -> {
                        if ("setFormat".equals(method.getName()) && args[0] instanceof FormatItem
                                && ((FormatItem) args[0]).getType() == FormatItem.TYPE_SUBTITLE) {
                            subtitlesSet.add((FormatItem) args[0]);
                        } else if ("getSubtitleFormat".equals(method.getName())) {
                            return selectedSubtitle;
                        } else if ("getVideo".equals(method.getName())) {
                            return mVideo;
                        }

                        Class<?> type = method.getReturnType();

                        if (type == boolean.class) {
                            return false;
                        } else if (type == int.class) {
                            return 0;
                        } else if (type == long.class) {
                            return 0L;
                        } else if (type == float.class) {
                            return 0f;
                        } else if (type == double.class) {
                            return 0d;
                        }

                        return null;
                    });
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }

        @Override
        public Video getVideo() {
            return mVideo;
        }
    }
}
