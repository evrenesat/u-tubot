package com.liskovsoft.smartyoutubetv2.tv.utubot.harness;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.google.android.exoplayer2.SimpleExoPlayer;
import com.google.android.exoplayer2.trackselection.AdaptiveTrackSelection;
import com.google.android.exoplayer2.trackselection.DefaultTrackSelector;
import com.google.android.exoplayer2.ui.PlayerView;
import com.google.android.exoplayer2.ui.SubtitleView;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.listener.PlayerEventListener;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.controller.ExoPlayerController;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.ExoPlayerInitializer;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.other.SubtitleManager;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.versions.renderer.CustomOverridesRenderersFactory;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.versions.selector.RestoreTrackSelector;

import java.lang.reflect.Proxy;
import java.util.Collections;
import java.util.List;

/**
 * Debug builds only. Plays a media file of the developer's own (a local server's, the one of scripts/emulator_mock_backend.py) through the
 * real {@link ExoPlayerController} and track selection, with the app's subtitle view, so the HQ captions can be checked on an emulator
 * without YouTube (docs/development.md, "Checking the HQ captions"). The player view is the app's engine, not its screens: no
 * controls, no history, no metadata.
 *
 * <pre>
 * adb shell am start -n dev.utubot.tv/com.liskovsoft.smartyoutubetv2.tv.utubot.harness.CaptionsHarnessActivity \
 *     --es video_id offlineCapA --es url http://10.0.2.2:18790/media/test.mp4
 * </pre>
 *
 * Up and Down pick the next and the previous subtitle format, like the subtitle menu does.
 */
public class CaptionsHarnessActivity extends Activity {
    private static final String EXTRA_VIDEO_ID = "video_id";
    private static final String EXTRA_URL = "url";
    private static final int STATUS_INTERVAL_MS = 500;
    private static final int STATUS_TEXT_SIZE_SP = 18;
    private static final int STATUS_PADDING_PX = 24;
    private static final int STATUS_BACKGROUND = 0xAA000000;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final Runnable mShowStatus = this::showStatus;
    private ExoPlayerInitializer mInitializer;
    private ExoPlayerController mController;
    private TextView mStatus;
    private String mLastSelection = "";
    /** The controller keeps the video weakly: the screens of the app hold it, here this does */
    private Video mVideo;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String videoId = getIntent().getStringExtra(EXTRA_VIDEO_ID);
        String url = getIntent().getStringExtra(EXTRA_URL);

        if (videoId == null || url == null) {
            finish();
            return;
        }

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        PlayerView playerView = new PlayerView(this);
        playerView.setUseController(false);
        root.addView(playerView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        SubtitleView subtitleView = new SubtitleView(this);
        root.addView(subtitleView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
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
        playerView.getSubtitleView().setVisibility(android.view.View.GONE);
        SubtitleManager subtitleManager = new SubtitleManager(subtitleView);
        player.getTextComponent().addTextOutput(subtitleManager);
        subtitleManager.show(true);

        mVideo = new Video();
        mVideo.videoId = videoId;
        mController.setVideo(mVideo);
        mController.openUrlList(Collections.singletonList(url));
        mHandler.post(mShowStatus);
    }

    @Override
    protected void onDestroy() {
        mHandler.removeCallbacks(mShowStatus);

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
        if (mController != null && (keyCode == KeyEvent.KEYCODE_DPAD_DOWN || keyCode == KeyEvent.KEYCODE_DPAD_UP)) {
            selectNeighbour(keyCode == KeyEvent.KEYCODE_DPAD_DOWN ? 1 : -1);
            return true;
        }

        return super.onKeyDown(keyCode, event);
    }

    private void selectNeighbour(int step) {
        List<FormatItem> formats = mController.getSubtitleFormats();

        if (formats == null || formats.isEmpty()) {
            return;
        }

        int selected = 0;

        for (int i = 0; i < formats.size(); i++) {
            if (formats.get(i).isSelected()) {
                selected = i;
            }
        }

        mController.selectFormat(formats.get(Math.floorMod(selected + step, formats.size())));
    }

    private void showStatus() {
        StringBuilder text = new StringBuilder("position ").append(mController.getPositionMs() / 1000).append(" s\nsubtitles:");
        List<FormatItem> formats = mController.getSubtitleFormats();

        if (formats != null) {
            for (FormatItem format : formats) {
                text.append("\n  ").append(format.isSelected() ? "(x) " : "( ) ").append(format.isDefault() ? "Subtitles disabled" : format.getTitle());
            }
        }

        String shown = text.toString();

        if (!shown.equals(mLastSelection)) {
            mLastSelection = shown;
            mStatus.setText(shown);
        }

        mHandler.postDelayed(mShowStatus, STATUS_INTERVAL_MS);
    }

    /**
     * Every event of the player is ignored: what the harness shows it reads from the controller
     */
    private static PlayerEventListener noOpListener() {
        return (PlayerEventListener) Proxy.newProxyInstance(PlayerEventListener.class.getClassLoader(), new Class<?>[]{PlayerEventListener.class},
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
