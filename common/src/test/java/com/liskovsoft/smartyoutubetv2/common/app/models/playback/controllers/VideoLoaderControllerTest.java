package com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers;

import android.os.Looper;

import com.liskovsoft.mediaserviceinterfaces.data.MediaItemFormatInfo;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager.PlayerConstants;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.service.VideoStateService;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.PlayerFailure;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.PlayerFailureLog;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.robolectric.Shadows.shadowOf;

/**
 * A live stream a client answered OK for with nothing to play it from (e.g. TV's for some music channels, SmartTube #6393)
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class VideoLoaderControllerTest {
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private PlayerFailureLog mLog;
    private int mSavedEngine;

    @Before
    public void setUp() {
        mLog = PlayerFailureLog.useForTesting(mFolder.getRoot());
        // Cronet can't load under Robolectric
        mSavedEngine = PlayerTweaksData.instance(RuntimeEnvironment.getApplication()).getPlayerDataSource();
        PlayerTweaksData.instance(RuntimeEnvironment.getApplication()).setPlayerDataSource(PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP);
    }

    @After
    public void tearDown() {
        PlayerFailureLog.useForTesting(null);
        PlayerTweaksData.instance(RuntimeEnvironment.getApplication()).setPlayerDataSource(mSavedEngine);
    }

    /**
     * The clients after it are tried, a few: then it's only reloaded, as before
     */
    @Test
    public void aLiveStreamWithNothingToPlaySwitchesTheClientAFewTimes() throws Exception {
        TestController controller = new TestController(video("WsDyRAPFBC8"));
        MediaItemFormatInfo live = formatInfo(true, "OK");

        assertTrue(isLiveClientToSwitch(controller, live));
        assertTrue(isLiveClientToSwitch(controller, live));
        assertTrue(isLiveClientToSwitch(controller, live));
        assertFalse(isLiveClientToSwitch(controller, live));

        // Another live stream: its own tries
        assertTrue(isLiveClientToSwitch(new TestController(video("d8Oc90QevaI")), live));
    }

    /**
     * Opened again, or another live stream of the channel: straight to the client that came after the first
     */
    @Test
    public void aLiveStreamTheFirstClientHadNothingForStartsOnTheNextOne() throws Exception {
        Map<String, Object> values = new HashMap<>();
        values.put("isLive", true);
        values.put("getPlayabilityStatus", "OK");
        values.put("getChannelId", "channel");
        TestController controller = new TestController(video("WsDyRAPFBC8"));
        assertTrue(isLiveClientToSwitch(controller, formatInfo(values)));

        // Left for another video: the switch is undone, and only that
        Video other = video("regular");
        resetLiveClientSwitch(controller, other);
        assertNull(getField(controller, "mLiveSwitchVideoId"));

        // The same stream, not known as live yet (e.g. a link)
        resetLiveClientSwitch(controller, video("WsDyRAPFBC8"));
        assertEquals("WsDyRAPFBC8", getField(controller, "mLiveSwitchVideoId"));
        assertEquals(1, getField(controller, "mLiveClientSwitches"));

        resetLiveClientSwitch(controller, other);

        // The channel's: only when live, a regular video of it plays on the first client
        Video channelVideo = video("channelVideo");
        channelVideo.channelId = "channel";
        resetLiveClientSwitch(controller, channelVideo);
        assertNull(getField(controller, "mLiveSwitchVideoId"));

        Video channelLive = video("channelLive");
        channelLive.channelId = "channel";
        channelLive.isLive = true;
        resetLiveClientSwitch(controller, channelLive);
        assertEquals("channelLive", getField(controller, "mLiveSwitchVideoId"));
    }

    /**
     * None of them had it: nothing's known to work for the next time
     */
    @Test
    public void aLiveStreamNoClientHadIsNotRemembered() throws Exception {
        TestController controller = new TestController(video("WsDyRAPFBC8"));
        MediaItemFormatInfo live = formatInfo(true, "OK");

        for (int i = 0; i < 4; i++) {
            isLiveClientToSwitch(controller, live);
        }

        assertTrue(((Map<?, ?>) getField(controller, "mLiveSwitches")).isEmpty());
    }

    /**
     * Not live (e.g. a premiere yet to start), or not playable as the client says: no other client has it either
     */
    @Test
    public void onlyALiveStreamThatPlaysSwitchesTheClient() throws Exception {
        TestController controller = new TestController(video("upcoming"));

        assertFalse(isLiveClientToSwitch(controller, formatInfo(false, "OK")));
        assertFalse(isLiveClientToSwitch(controller, formatInfo(true, "LIVE_STREAM_OFFLINE")));
    }

    /**
     * What the answer had, of what the player plays from: tells TV's SABR-only answer from an empty one
     */
    @Test
    public void anEmptyFormatsFailureSaysWhatTheFormatsHad() throws Exception {
        Map<String, Object> values = new HashMap<>();
        values.put("isLive", true);
        values.put("getStartTimeMs", 0L);
        values.put("containsSabrFormats", true);
        values.put("getServerAbrStreamingUrl", "https://rr1---sn-test.googlevideo.com/videoplayback");
        PlayerFailure failure = PlayerFailure.create(RuntimeEnvironment.getApplication(), PlayerFailure.KIND_EMPTY_FORMATS);

        Method method = VideoLoaderController.class.getDeclaredMethod("addMediaDetails", PlayerFailure.class, MediaItemFormatInfo.class);
        method.setAccessible(true);
        method.invoke(null, failure, formatInfo(values));
        failure.record();

        JSONObject details = mLog.readAll().get(0).getJSONObject("details");
        assertTrue(details.getBoolean("live"));
        assertEquals(0, details.getLong("startTimeMs"));
        assertTrue(details.getBoolean("sabrFormats"));
        assertFalse(details.getBoolean("dashFormats"));
        assertFalse(details.getBoolean("hlsManifest"));
        assertFalse(details.getBoolean("dashManifest"));
        assertFalse(details.getBoolean("urlFormats"));
        assertTrue(details.getBoolean("serverAbrUrl"));
    }

    /**
     * Played again after its streams expired (e.g. a night's pause, K3F6GAY6 #15): fetched again first, once for those formats
     */
    @Test
    public void playedAgainWithItsStreamsExpiringItsFetchedAgain() throws Exception {
        PlayingController controller = new PlayingController(video("bNAlycU0Xzg"));
        setFormats(controller, "bNAlycU0Xzg", System.currentTimeMillis() + MediaItemFormatInfo.STREAMS_EXPIRE_MARGIN_MS - 1_000);

        controller.onPlay();
        controller.onPlay();

        assertEquals(1, controller.mReloads);
    }

    @Test
    public void playedAgainWithTimeLeftItPlaysOn() throws Exception {
        PlayingController controller = new PlayingController(video("bNAlycU0Xzg"));
        setFormats(controller, "bNAlycU0Xzg", System.currentTimeMillis() + 2 * MediaItemFormatInfo.STREAMS_EXPIRE_MARGIN_MS);
        controller.onPlay();

        // Unknown, or of another video
        setFormats(controller, "bNAlycU0Xzg", 0);
        controller.onPlay();
        setFormats(controller, "another", System.currentTimeMillis() - 1_000);
        controller.onPlay();

        // A live stream's manifest is fetched again by the player
        PlayingController live = new PlayingController(video("WsDyRAPFBC8"));
        live.getVideo().isLive = true;
        setFormats(live, "WsDyRAPFBC8", System.currentTimeMillis() - 1_000);
        live.onPlay();

        assertEquals(0, controller.mReloads);
        assertEquals(0, live.mReloads);
    }

    /**
     * A stopped video is left a second before its end. At its length, whole seconds past its media (9lKpEOEbr0U: 1972 s of
     * 1971.719 s), the player never got ready over DASH, and the stall check reloaded it from 0:00
     */
    @Test
    public void aStoppedVideoIsLeftASecondBeforeItsEnd() throws Exception {
        assertEquals(1_971_000L, stopPlayback(video("9lKpEOEbr0U"), 1_972_000));
    }

    @Test
    public void aStoppedLiveStreamIsLeftAtItsEnd() throws Exception {
        Video live = video("WsDyRAPFBC8");
        live.isLive = true;

        assertEquals(7_200_000L, stopPlayback(live, 7_200_000));
    }

    /**
     * Not known yet (unset), or too short to go back from: where it was left before
     */
    @Test
    public void aStoppedVideoWithoutALengthToGoBackFromIsLeftAtItsEnd() throws Exception {
        assertEquals(-1L, stopPlayback(video("unknown"), -1));
        assertEquals(800L, stopPlayback(video("short"), 800));
    }

    /**
     * A reload marks the video it opens again: it stays where it was (see VideoStateController)
     */
    @Test
    public void aReloadMarksTheVideoItOpensAgain() {
        Video video = video("9lKpEOEbr0U");
        Video[] opened = {null};
        PlaybackView player = stub(PlaybackView.class, Collections.<String, Object>singletonMap("isEngineInitialized", true));
        TestController controller = new TestController(video) {
            @Override
            public PlaybackView getPlayer() {
                return player;
            }

            @Override
            protected PlayerEventListener getMainController() {
                return (PlayerEventListener) Proxy.newProxyInstance(PlayerEventListener.class.getClassLoader(),
                        new Class<?>[]{PlayerEventListener.class}, (proxy, method, args) -> {
                            if ("onNewVideo".equals(method.getName())) {
                                opened[0] = (Video) args[0];
                            }

                            return method.getReturnType() == boolean.class ? false : null;
                        });
            }
        };

        controller.reloadVideo(0);
        shadowOf(Looper.getMainLooper()).idle();

        assertTrue(opened[0] == video && video.fromReload);
    }

    /**
     * E3RZYG50: "Premieres in 88 minutes" was reloaded every 30 s. Reloaded after half the time left, 10 min at most: the reload after
     * it starts comes 30 s after at most.
     */
    @Test
    public void aPremiereIsReloadedAfterHalfTheTimeLeft() {
        long nowMs = 1_793_975_507_000L; // 2026-11-06T14:31:47Z
        MediaItemFormatInfo inAnHour = premiere("2026-11-06T15:31:47+00:00");
        MediaItemFormatInfo in6Minutes = premiere("2026-11-06T14:37:47+00:00");
        MediaItemFormatInfo inAMinute = premiere("2026-11-06T14:32:47+00:00");

        assertEquals(10 * 60_000, VideoLoaderController.getEmptyFormatsReloadMs(inAnHour, nowMs));
        assertEquals(3 * 60_000, VideoLoaderController.getEmptyFormatsReloadMs(in6Minutes, nowMs));
        assertEquals(30_000, VideoLoaderController.getEmptyFormatsReloadMs(inAMinute, nowMs));
    }

    /**
     * Past its time (it's late), or with none, it's reloaded every 30 s, as one with no formats is
     */
    @Test
    public void aPremiereWithoutTimeLeftIsReloadedEvery30Seconds() {
        long nowMs = 1_793_975_507_000L; // 2026-11-06T14:31:47Z

        assertEquals(30_000, VideoLoaderController.getEmptyFormatsReloadMs(premiere("2026-11-06T14:00:00+00:00"), nowMs));
        assertEquals(30_000, VideoLoaderController.getEmptyFormatsReloadMs(premiere(null), nowMs));
        assertEquals(30_000, VideoLoaderController.getEmptyFormatsReloadMs(premiere("not a time"), nowMs));
    }

    /**
     * The start time of a video that isn't waiting to start doesn't make it wait longer
     */
    @Test
    public void aVideoWithNoFormatsIsReloadedEvery30Seconds() {
        Map<String, Object> values = new HashMap<>();
        values.put("getPlayabilityStatus", "OK");
        values.put("getStartTimestamp", "2026-11-06T15:31:47+00:00");

        assertEquals(30_000, VideoLoaderController.getEmptyFormatsReloadMs(formatInfo(values), 1_793_975_507_000L));
        assertFalse(VideoLoaderController.isUpcoming(formatInfo(values)));
        assertTrue(VideoLoaderController.isUpcoming(premiere(null)));
    }

    /**
     * Repeat one after an error ended the video (see ErrorFixerController#runEngineErrorAction): the player is idle, where a seek
     * doesn't play. Reloaded from its start.
     */
    @Test
    public void repeatOneOfAVideoAnErrorEndedReloadsItFromItsStart() throws Exception {
        RepeatController controller = new RepeatController(video("9TJXo63g6JA"), false);

        applyPlaybackMode(controller, PlayerConstants.PLAYBACK_MODE_ONE);

        assertEquals(1, controller.mReloads);
        assertTrue(controller.mSeeks.isEmpty());
        assertEquals(0, VideoStateService.instance(RuntimeEnvironment.getApplication()).getByVideoId("9TJXo63g6JA").positionMs);
    }

    /**
     * Ended as usual: back to its start in the same player
     */
    @Test
    public void repeatOneOfAVideoThatEndedSeeksToItsStart() throws Exception {
        RepeatController controller = new RepeatController(video("b1Cchyj6bZw"), true);

        applyPlaybackMode(controller, PlayerConstants.PLAYBACK_MODE_ONE);

        assertEquals(0, controller.mReloads);
        assertEquals(Collections.singletonList(0L), controller.mSeeks);
    }

    private static void applyPlaybackMode(TestController controller, int playbackMode) throws Exception {
        Method method = VideoLoaderController.class.getDeclaredMethod("applyPlaybackModeInt", Video.class, int.class);
        method.setAccessible(true);
        method.invoke(controller, controller.getVideo(), playbackMode);
    }

    private static MediaItemFormatInfo premiere(String startTimestamp) {
        Map<String, Object> values = new HashMap<>();
        values.put("getPlayabilityStatus", "LIVE_STREAM_OFFLINE");
        values.put("getPlayabilityReason", "Premieres in 88 minutes");
        values.put("getStartTimestamp", startTimestamp);

        return formatInfo(values);
    }

    /**
     * @return where the player was sent
     */
    private static long stopPlayback(Video video, long durationMs) throws Exception {
        long[] positionMs = {Long.MIN_VALUE};
        PlaybackView player = (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                (proxy, method, args) -> {
                    if ("getDurationMs".equals(method.getName())) {
                        return durationMs;
                    } else if ("setPositionMs".equals(method.getName())) {
                        positionMs[0] = (long) args[0];
                    }

                    return method.getReturnType() == boolean.class ? false : null;
                });
        TestController controller = new TestController(video) {
            @Override
            public PlaybackView getPlayer() {
                return player;
            }
        };

        Method method = VideoLoaderController.class.getDeclaredMethod("stopPlayback");
        method.setAccessible(true);
        method.invoke(controller);

        return positionMs[0];
    }

    private static void setFormats(VideoLoaderController controller, String videoId, long streamsExpireTimeMs) throws Exception {
        setField(controller, "mFormatVideoId", videoId);
        setField(controller, "mStreamsExpireTimeMs", streamsExpireTimeMs);
    }

    private static void setField(VideoLoaderController controller, String name, Object value) throws Exception {
        java.lang.reflect.Field field = VideoLoaderController.class.getDeclaredField(name);
        field.setAccessible(true);
        field.set(controller, value);
    }

    private static boolean isLiveClientToSwitch(VideoLoaderController controller, MediaItemFormatInfo formatInfo) throws Exception {
        Method method = VideoLoaderController.class.getDeclaredMethod("isLiveClientToSwitch", MediaItemFormatInfo.class);
        method.setAccessible(true);

        return (boolean) method.invoke(controller, formatInfo);
    }

    private static void resetLiveClientSwitch(VideoLoaderController controller, Video video) throws Exception {
        Method method = VideoLoaderController.class.getDeclaredMethod("resetLiveClientSwitch", Video.class);
        method.setAccessible(true);
        method.invoke(controller, video);
    }

    private static Object getField(VideoLoaderController controller, String name) throws Exception {
        java.lang.reflect.Field field = VideoLoaderController.class.getDeclaredField(name);
        field.setAccessible(true);

        return field.get(controller);
    }

    private static MediaItemFormatInfo formatInfo(boolean isLive, String status) {
        Map<String, Object> values = new HashMap<>();
        values.put("isLive", isLive);
        values.put("getPlayabilityStatus", status);

        return formatInfo(values);
    }

    /**
     * By method name; the defaults (false, 0, null) for the others
     */
    private static MediaItemFormatInfo formatInfo(Map<String, Object> values) {
        return stub(MediaItemFormatInfo.class, values);
    }

    /**
     * By method name; the defaults (false, 0, null) for the others
     */
    private static <T> T stub(Class<T> type, Map<String, Object> values) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (proxy, method, args) -> {
            if (values.containsKey(method.getName())) {
                return values.get(method.getName());
            }

            Class<?> returned = method.getReturnType();

            if (returned == boolean.class) {
                return false;
            } else if (returned == int.class) {
                return 0;
            } else if (returned == long.class) {
                return 0L;
            } else if (returned == float.class) {
                return 0f;
            }

            return null;
        }));
    }

    private static Video video(String videoId) {
        Video video = new Video();
        video.videoId = videoId;
        return video;
    }

    /**
     * A film opens as one progressive source: no YouTube formats are fetched (that would reach the YouTube service), the film is not queued
     * and a next or previous press does nothing
     */
    @Test
    public void aFilmOpensItsStreamDirectly() throws Exception {
        Video film = Video.fromFilm(new com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmPlay("tt1", "movie", "tt1", "Heat", null, 0, 0,
                "https://host/key/file.mkv", "Heat 2160p DV HDR", 0, 0));
        List<String> calls = new ArrayList<>();
        PlaybackView player = (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                (proxy, method, args) -> {
                    calls.add(method.getName() + (args != null && args.length == 1 && args[0] instanceof String ? ":" + args[0] : ""));
                    return method.getReturnType() == boolean.class ? false : null;
                });
        TestController controller = new TestController(film) {
            {
                setAltContext(RuntimeEnvironment.getApplication());
            }

            @Override
            public PlaybackView getPlayer() {
                return player;
            }
        };

        Method load = VideoLoaderController.class.getDeclaredMethod("loadVideo", Video.class);
        load.setAccessible(true);
        load.invoke(controller, film);

        assertTrue(calls.contains("openProgressiveUrl:https://host/key/file.mkv"));
        assertFalse(calls.contains("openDash"));
        assertEquals(film.videoId, getField(controller, "mFormatVideoId"));
        assertEquals("progressive", getField(controller, "mFormatProtocol"));
        assertTrue(controller.onNextClicked());
        assertTrue(controller.onPreviousClicked());
    }

    private static class TestController extends VideoLoaderController {
        private final Video mVideo;

        private TestController(Video video) {
            mVideo = video;
        }

        @Override
        public Video getVideo() {
            return mVideo;
        }
    }

    /**
     * At the end of a 3:21.8 video: its seeks and reloads are counted, not done
     */
    private static class RepeatController extends TestController {
        private final List<Long> mSeeks = new ArrayList<>();
        private final PlaybackView mPlayer;
        private int mReloads;

        /**
         * @param containsMedia false for a player an error left idle
         */
        private RepeatController(Video video, boolean containsMedia) {
            super(video);
            setAltContext(RuntimeEnvironment.getApplication());
            Map<String, Object> values = new HashMap<>();
            values.put("containsMedia", containsMedia);
            values.put("getDurationMs", 201_800L);
            values.put("getPositionMs", 201_300L);
            values.put("getSpeed", 1.0f);
            PlaybackView stub = stub(PlaybackView.class, values);
            mPlayer = (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                    (proxy, method, args) -> {
                        if ("setPositionMs".equals(method.getName())) {
                            mSeeks.add((long) args[0]);
                        }

                        return method.invoke(stub, args);
                    });
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }

        @Override
        public void reloadVideo(int delayMs) {
            mReloads++;
        }
    }

    /**
     * With a player: its reloads are counted, not done
     */
    private static class PlayingController extends TestController {
        private final PlaybackView mPlayer = stub(PlaybackView.class, new HashMap<>());
        private int mReloads;

        private PlayingController(Video video) {
            super(video);
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }

        @Override
        public void reloadVideo(int delayMs) {
            mReloads++;
        }
    }
}
