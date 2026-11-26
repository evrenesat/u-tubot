package com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers;

import android.content.Context;

import com.liskovsoft.mediaserviceinterfaces.data.SponsorSegment;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs;
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutController;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * While a u·tubot director's cut is applied to the video that plays, the sponsor block is fully off: it neither skips nor prompts, so it
 * does not fight the cut over the same section (u·tubot#145). The suppression holds for a sponsor segment inside a cut-out part, one at
 * its start and one straddling it, and the skipping comes back the moment the cut is off or the video has no active cut.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class SponsorBlockControllerTest {
    private static final String VIDEO = "abcdefghijk";
    // A cut-out part of the video, and sponsor segments overlapping it three ways.
    private static final long CUT_START = 60_000;
    private static final long CUT_END = 108_000;
    private static final long INSIDE_START = 70_000;
    private static final long INSIDE_END = 90_000;
    private static final long AT_START_START = 54_000;
    private static final long AT_START_END = 66_000;
    private static final long STRADDLE_START = 100_000;
    private static final long STRADDLE_END = 120_000;

    private Context mContext;

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.getApplication();
        AppPrefs.instance(mContext).onAccountChanged(null);
        SponsorBlockData.instance(mContext).setAction(SponsorSegment.CATEGORY_SPONSOR, SponsorBlockData.ACTION_SKIP_ONLY);
    }

    /**
     * A sponsor segment fully inside the cut-out part: with a cut applied the sponsor block skips nothing, without one it skips to the
     * end of the segment.
     */
    @Test
    public void aSponsorSegmentInsideACutOutPart_isNotSkippedWhileACutIsApplied() throws Exception {
        List<SponsorSegment> segment = sponsorRange(INSIDE_START, INSIDE_END);

        assertFalse(skipsAt(INSIDE_START, segment, cut(true))); // a director's cut is on: the sponsor block stays off
        assertTrue(skipsAt(INSIDE_START, segment, cut(false))); // off again: the sponsor block skips the segment to its end
    }

    /**
     * A sponsor segment that starts before the cut-out part and overlaps into it: not skipped while a cut is applied, skipped otherwise.
     */
    @Test
    public void aSponsorSegmentAtTheStartOfACutOutPart_isNotSkippedWhileACutIsApplied() throws Exception {
        List<SponsorSegment> segment = sponsorRange(AT_START_START, AT_START_END);

        assertFalse(skipsAt(AT_START_START, segment, cut(true)));
        assertTrue(skipsAt(AT_START_START, segment, cut(false)));
    }

    /**
     * A sponsor segment that straddles the end of the cut-out part: not skipped while a cut is applied, skipped otherwise.
     */
    @Test
    public void aSponsorSegmentStraddlingACutOutPart_isNotSkippedWhileACutIsApplied() throws Exception {
        List<SponsorSegment> segment = sponsorRange(STRADDLE_START, STRADDLE_END);

        assertFalse(skipsAt(STRADDLE_START, segment, cut(true)));
        assertTrue(skipsAt(STRADDLE_START, segment, cut(false)));
    }

    /**
     * Several overlapping segments at once: the cut being on suppresses every one of them, the cut being off skips the first crossed.
     */
    @Test
    public void severalOverlappingSegments_areAllSuppressedWhileACutIsApplied() throws Exception {
        List<SponsorSegment> segments = new ArrayList<>();
        segments.add(sponsor(INSIDE_START, INSIDE_END));
        segments.add(sponsor(AT_START_START, AT_START_END));
        segments.add(sponsor(STRADDLE_START, STRADDLE_END));

        assertFalse(skipsAt(INSIDE_START, segments, cut(true)));

        List<SponsorSegment> segmentsFree = new ArrayList<>(segments);
        assertTrue(skipsAt(INSIDE_START, segmentsFree, cut(false)));
    }

    /**
     * No cut controller registered (the built-in flavor is off): the hook is inert and the sponsor block skips as before.
     */
    @Test
    public void withoutACutController_theSponsorBlockSkipsAsBefore() throws Exception {
        assertTrue(skipsAt(INSIDE_START, sponsorRange(INSIDE_START, INSIDE_END), null));
    }

    private boolean skipsAt(long positionMs, List<SponsorSegment> segments, UtubotCutController cut) throws Exception {
        TestSponsorBlockController controller = new TestSponsorBlockController();
        controller.init(mContext, 600_000);
        controller.loadSegments(VIDEO, segments);
        controller.attachCut(cut);
        controller.skipAt(positionMs);
        return controller.skipped();
    }

    /**
     * A cut controller with an applied cut (the video that plays), or one without a cut, or none at all: the three states
     * {@link SponsorBlockController#isCutActive} distinguishes.
     */
    private static UtubotCutController cut(boolean active) throws Exception {
        UtubotCutController controller = new UtubotCutController();

        if (active) {
            Cut cut = new Cut();
            cut.videoId = VIDEO;
            Field cutField = UtubotCutController.class.getDeclaredField("mCut");
            cutField.setAccessible(true);
            cutField.set(controller, cut);
        }

        return controller;
    }

    private static List<SponsorSegment> sponsorRange(long startMs, long endMs) {
        return Collections.singletonList(sponsor(startMs, endMs));
    }

    private static SponsorSegment sponsor(long startMs, long endMs) {
        return new SponsorSegment() {
            @Override
            public long getStartMs() {
                return startMs;
            }

            @Override
            public long getEndMs() {
                return endMs;
            }

            @Override
            public String getCategory() {
                return SponsorSegment.CATEGORY_SPONSOR;
            }

            @Override
            public String getAction() {
                return "skip";
            }
        };
    }

    /**
     * A sponsor block with its own video, player and (fake) cut controller, so the real {@link SponsorBlockController#skipSegment} runs
     * against them. The seeks it makes are counted, not performed.
     */
    private static final class TestSponsorBlockController extends SponsorBlockController {
        private final Video mVideo = video(VIDEO);
        private PlaybackView mPlayer;
        private long mPositionMs;
        private final List<Long> mSeeks = new ArrayList<>();
        private UtubotCutController mCut;

        void init(Context context, long durationMs) {
            setAltContext(context);
            mPositionMs = 0;
            mSeeks.clear();
            mPlayer = (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                    (proxy, method, args) -> {
                        switch (method.getName()) {
                            case "isPlaying":
                                return true;
                            case "getPositionMs":
                                return mPositionMs;
                            case "getSpeed":
                                return 1f;
                            case "getDurationMs":
                                return durationMs;
                            case "setPositionMs":
                                mSeeks.add((long) args[0]);
                                return null;
                            case "isInPIPMode":
                                return false;
                            case "isEmbed":
                                return false;
                            case "isSuggestionsShown":
                                return false;
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
                        }

                        return null;
                    });
        }

        void loadSegments(String videoId, List<SponsorSegment> segments) throws Exception {
            Field segmentsField = SponsorBlockController.class.getDeclaredField("mActiveSegments");
            segmentsField.setAccessible(true);
            segmentsField.set(this, segments);

            Field videoField = SponsorBlockController.class.getDeclaredField("mVideoId");
            videoField.setAccessible(true);
            videoField.set(this, videoId);
        }

        void attachCut(UtubotCutController cut) {
            mCut = cut;
        }

        void skipAt(long positionMs) throws Exception {
            mPositionMs = positionMs;
            Method skip = SponsorBlockController.class.getDeclaredMethod("skipSegment", long.class);
            skip.setAccessible(true);
            skip.invoke(this, 0L);
        }

        boolean skipped() {
            return !mSeeks.isEmpty();
        }

        @Override
        public Video getVideo() {
            return mVideo;
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }

        @Override
        protected <T extends PlayerEventListener> T getController(Class<T> clazz) {
            return clazz == UtubotCutController.class ? (T) mCut : null;
        }
    }

    private static Video video(String videoId) {
        Video video = new Video();
        video.videoId = videoId;
        return video;
    }
}
