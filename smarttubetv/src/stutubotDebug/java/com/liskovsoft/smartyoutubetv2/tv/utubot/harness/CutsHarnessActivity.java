package com.liskovsoft.smartyoutubetv2.tv.utubot.harness;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.google.android.exoplayer2.SimpleExoPlayer;
import com.google.android.exoplayer2.trackselection.AdaptiveTrackSelection;
import com.google.android.exoplayer2.trackselection.DefaultTrackSelector;
import com.google.android.exoplayer2.ui.PlayerView;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers.SponsorBlockController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.controller.ExoPlayerController;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.ExoPlayerInitializer;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.versions.renderer.CustomOverridesRenderersFactory;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.versions.selector.RestoreTrackSelector;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutController;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutSkipper;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotMeta;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Collections;

import io.reactivex.disposables.Disposable;

/**
 * Debug builds only. Plays a media file of the developer's own (a local server's, the one of scripts/emulator_mock_backend.py) through
 * the real engine and the real director's-cut flow: the {@link PlaybackPresenter}'s {@link UtubotCutController} and
 * SponsorBlockController receive the playback events and skip with the real skip logic, so the cuts can be checked on an emulator
 * without YouTube (docs/development.md, "Checking the director's cuts"). The player view is the app's engine, not its screens: no
 * controls, no seek bar.
 *
 * <pre>
 * adb shell am start -n dev.utubot.tv/com.liskovsoft.smartyoutubetv2.tv.utubot.harness.CutsHarnessActivity \
 *     --es video_id harnessCutA --es url http://10.0.2.2:18790/media/test.mp4 \
 *     [--ei start_ms 55000] [--es request_preset cut-no-filler] [--ez await_prompt false]
 * </pre>
 *
 * Right and Left seek 30 s back and forth, like the player does; every status line also goes to the log (tag {@link #TAG}).
 */
public class CutsHarnessActivity extends Activity {
    private static final String TAG = "UtubotCutsHarness";
    private static final String EXTRA_VIDEO_ID = "video_id";
    private static final String EXTRA_URL = "url";
    private static final String EXTRA_START_MS = "start_ms";
    private static final String EXTRA_REQUEST_PRESET = "request_preset";
    private static final String EXTRA_AWAIT_PROMPT = "await_prompt";
    private static final int SEEK_STEP_MS = 30_000;
    private static final int STATUS_INTERVAL_MS = 500;
    private static final int STATUS_TEXT_SIZE_SP = 18;
    private static final int STATUS_PADDING_PX = 24;
    private static final int STATUS_BACKGROUND = 0xAA000000;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final Runnable mShowStatus = this::showStatus;
    private ExoPlayerInitializer mInitializer;
    private ExoPlayerController mController;
    private UtubotCutController mCutController;
    private TextView mStatus;
    private String mLastStatus = "";
    private String mVideoId;
    /** The controller keeps the video weakly: the screens of the app hold it, here this does */
    private Video mVideo;
    private long mStartMs;
    private boolean mSeeked;
    private Disposable mRequestAction;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        mVideoId = getIntent().getStringExtra(EXTRA_VIDEO_ID);
        String url = getIntent().getStringExtra(EXTRA_URL);
        mStartMs = getIntent().getIntExtra(EXTRA_START_MS, 0);
        String requestPreset = getIntent().getStringExtra(EXTRA_REQUEST_PRESET);
        boolean awaitPrompt = getIntent().getBooleanExtra(EXTRA_AWAIT_PROMPT, false);

        if (mVideoId == null || url == null) {
            finish();
            return;
        }

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        PlayerView playerView = new PlayerView(this);
        playerView.setUseController(false);
        root.addView(playerView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        mStatus = new TextView(this);
        mStatus.setTextColor(Color.WHITE);
        mStatus.setBackgroundColor(STATUS_BACKGROUND);
        mStatus.setTextSize(STATUS_TEXT_SIZE_SP);
        mStatus.setPadding(STATUS_PADDING_PX, STATUS_PADDING_PX, STATUS_PADDING_PX, STATUS_PADDING_PX);
        root.addView(mStatus, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.START));
        setContentView(root);

        mInitializer = new ExoPlayerInitializer(this);
        mController = new ExoPlayerController(this, noOpListener());
        DefaultTrackSelector trackSelector = new RestoreTrackSelector(new AdaptiveTrackSelection.Factory());
        mController.setTrackSelector(trackSelector);
        SimpleExoPlayer player = mInitializer.createPlayer(this, new CustomOverridesRenderersFactory(this), trackSelector);
        player.setPlayWhenReady(true);
        mController.setPlayer(player);
        playerView.setPlayer(player);

        // The playback controllers run on the app's presenter, whose player view is the engine of this harness
        PlaybackPresenter presenter = PlaybackPresenter.instance(this);
        presenter.setView(engineAsPlaybackView());
        mVideo = new Video();
        mVideo.videoId = mVideoId;
        holdVideo(presenter, mVideo);
        mCutController = presenter.getController(UtubotCutController.class);
        dispatchNewVideo(presenter);

        mController.setVideo(mVideo);
        mController.openUrlList(Collections.singletonList(url));
        mHandler.post(mShowStatus);

        if (requestPreset != null || awaitPrompt) {
            requestCut(requestPreset, awaitPrompt);
        }
    }

    @Override
    protected void onDestroy() {
        mHandler.removeCallbacks(mShowStatus);

        if (mRequestAction != null) {
            mRequestAction.dispose();
        }

        if (mCutController != null) {
            UtubotManager.instance(this).stopFollowingCuts(mCutController);
        }

        if (mController != null) {
            mController.release();
        }

        if (mInitializer != null) {
            mInitializer.release();
        }

        super.onDestroy();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (mController != null && keyCode == KeyEvent.KEYCODE_DPAD_RIGHT) {
            seek(SEEK_STEP_MS);
            return true;
        }

        if (mController != null && keyCode == KeyEvent.KEYCODE_DPAD_LEFT) {
            seek(-SEEK_STEP_MS);
            return true;
        }

        return super.onKeyDown(keyCode, event);
    }

    /**
     * A seek like the player's: the engine moves and the controllers hear that a seek ended
     */
    private void seek(int stepMs) {
        long to = Math.max(0, mController.getPositionMs() + stepMs);
        mController.setPositionMs(to);

        if (mCutController != null) {
            mCutController.onSeekEnd();
        }

        log("seek to " + to / 1000 + " s");
    }

    /**
     * The events a video open produces, straight to the controllers the cut runs on (the full dispatch would load the video's media
     * from YouTube, which the check must not do)
     */
    private void dispatchNewVideo(PlaybackPresenter presenter) {
        PlayerEventListener[] controllers = {presenter.getController(SponsorBlockController.class), mCutController};

        for (PlayerEventListener controller : controllers) {
            if (controller != null) {
                controller.onNewVideo(mVideo);
                controller.onEngineInitialized();
                controller.onVideoLoaded(mVideo);
            }
        }
    }

    /**
     * A cut request through the manager, the way the video menu's picker does it, without the menu's dialog
     */
    private void requestCut(@Nullable String presetId, boolean awaitPrompt) {
        mRequestAction = UtubotManager.instance(this)
                .requestCutObserve(mVideoId, presetId, null, awaitPrompt, UtubotMeta.from(mVideo))
                .subscribe(request -> {
                    log("requested " + request.id + " state " + request.state);
                    UtubotManager.instance(this).cutRequested(mVideoId, request.id, request.state);
                }, error -> log("request failed: " + error.getMessage()));
    }

    /**
     * The engine behind a {@link PlaybackView}: what the engine does is answered by it, what a playback screen would do is a no-op
     */
    private PlaybackView engineAsPlaybackView() {
        return (PlaybackView) Proxy.newProxyInstance(PlaybackView.class.getClassLoader(), new Class<?>[]{PlaybackView.class},
                (proxy, method, args) -> {
                    Method target = findEngineMethod(method);

                    if (target != null) {
                        return target.invoke(mController, args);
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

    @Nullable
    private static Method findEngineMethod(Method method) {
        try {
            return ExoPlayerController.class.getMethod(method.getName(), method.getParameterTypes());
        } catch (NoSuchMethodException e) {
            return null;
        }
    }

    /**
     * The screens of the app hold the video; the harness does it with the field the presenter reads the current video from
     */
    private static void holdVideo(PlaybackPresenter presenter, Video video) {
        try {
            Field field = PlaybackPresenter.class.getDeclaredField("mVideo");
            field.setAccessible(true);
            field.set(presenter, new WeakReference<>(video));
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Cannot hold the video of the harness", e);
        }
    }

    private void showStatus() {
        long positionSec = mController.getPositionMs() / 1000;
        long durationSec = mController.getDurationMs() / 1000;

        if (durationSec > 0 && mStartMs > 0 && !mSeeked && mController.isPlaying()) {
            mController.setPositionMs(mStartMs);
            mSeeked = true;
            log("start at " + mStartMs / 1000 + " s");
        }

        StringBuilder text = new StringBuilder("position ").append(positionSec).append(" s of ").append(durationSec).append(" s");
        Cut cut = activeCut();

        if (cut != null) {
            text.append("\ncut applied: ").append(cut.skipRangesMs.size()).append(" skips, keeps ")
                    .append(UtubotCutController.formatLength(cut.keptMs));
        } else {
            text.append("\ncut applied: none");
        }

        String shown = text.toString();

        if (!shown.equals(mLastStatus)) {
            mLastStatus = shown;
            mStatus.setText(shown);
            log("position=" + positionSec * 1000 + " " + shown.replace("\n", " | "));
        }

        mHandler.postDelayed(mShowStatus, STATUS_INTERVAL_MS);
    }

    @Nullable
    private Cut activeCut() {
        if (mCutController == null) {
            return null;
        }

        try {
            Field field = UtubotCutController.class.getDeclaredField("mCut");
            field.setAccessible(true);
            return (Cut) field.get(mCutController);
        } catch (ReflectiveOperationException e) {
            return null;
        }
    }

    private static void log(String message) {
        Log.i(TAG, message);
    }

    /**
     * Every event of the player is ignored: what the harness shows it reads from the controller
     */
    private static PlayerEventListener noOpListener() {
        return (PlayerEventListener) Proxy.newProxyInstance(PlayerEventListener.class.getClassLoader(),
                new Class<?>[]{PlayerEventListener.class},
                (proxy, method, args) -> {
                    Class<?> type = method.getReturnType();

                    if (type == boolean.class) {
                        return false;
                    } else if (type == int.class) {
                        return 0;
                    } else if (type == long.class) {
                        return 0L;
                    }

                    return null;
                });
    }
}