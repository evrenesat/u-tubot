package com.liskovsoft.smartyoutubetv2.tv.utubot.films;

import android.app.Activity;
import android.graphics.Color;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.Format;
import com.google.android.exoplayer2.SimpleExoPlayer;
import com.google.android.exoplayer2.analytics.AnalyticsListener;
import com.google.android.exoplayer2.video.ColorInfo;
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
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmDevice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmFormat;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsDeveloperPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsKeys;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotKeys;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient.Stream;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridSkips;

import io.reactivex.Observable;
import io.reactivex.schedulers.Schedulers;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;

import io.reactivex.disposables.Disposable;
import com.liskovsoft.sharedutils.rx.RxHelper;

/**
 * The film screen of the Real-Debrid spike (issue 211), reached from Settings, Updates, "Films (developer)" once the developer entry is on.
 * It lists the streams the configured Stremio addon returns for the IMDb id and plays the chosen one through the app's real player on the
 * progressive path, next to {@link ExoPlayerController#openUrlList}. A hand-written skip list, when set, is fed through the sponsor block so
 * cut-style playback is proven without building a director's cut.
 *
 * <p>The addon address and the Real-Debrid token come from {@link UtubotSettings}; stream addresses can carry a key, so neither they nor the
 * addon address are shown or logged. The screen closes at once when the developer entry is off.
 */
public class RealDebridFilmsActivity extends Activity {
    static final String EXTRA_TYPE = "type";
    static final String EXTRA_TITLE_ID = "title_id";
    static final String EXTRA_NAME = "name";
    static final String EXTRA_POSTER = "poster";
    static final String EXTRA_SEASON = "season";
    static final String EXTRA_EPISODE = "episode";
    static final String EXTRA_STREAM_URL = "stream_url";
    static final String EXTRA_STREAM_NAME = "stream_name";
    static final String EXTRA_START_MS = "start_ms";
    private static final String TAG = "UtubotRealDebridFilms";
    private static final long SAVE_INTERVAL_MS = 15_000;

    private static final int TEXT_SP = 18;
    private static final int ROW_PADDING = 16;

    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private UtubotSettings mSettings;
    private FrameLayout mRoot;
    private LinearLayout mPanel;
    private LinearLayout mList;
    private TextView mStatus;
    private ExoPlayerInitializer mInitializer;
    private ExoPlayerController mController;
    private SponsorBlockController mSponsorController;
    private PlaybackView mPlayback;
    private Video mVideo;
    private UtubotRealDebridClient mClient;
    private List<Stream> mStreams = new ArrayList<>();
    private List<TextView> mRows = new ArrayList<>();
    private int mFocusedIndex = -1;
    private Disposable mLoadAction;
    private boolean mLoaded;
    private boolean mPlaying;
    private UtubotFilmDevice mDevice;
    private SimpleExoPlayer mPlayer;
    private UtubotFilmsProgress mProgress;
    private String mStreamType = UtubotRealDebridClient.TYPE_MOVIE;
    private final Runnable mSaveTick = new Runnable() {
        @Override
        public void run() {
            saveProgress();
            mHandler.postDelayed(this, SAVE_INTERVAL_MS);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        mSettings = UtubotSettings.instance(this);
        mDevice = new UtubotFilmDevice(this);
        Log.i(TAG, "This TV: " + mDevice.describe());

        if (!mSettings.isFilmsDeveloperEnabled()) {
            finish();
            return;
        }

        mRoot = new FrameLayout(this);
        mRoot.setBackgroundColor(Color.BLACK);
        PlayerView playerView = new PlayerView(this);
        playerView.setUseController(false);
        mRoot.addView(playerView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        buildPanel();
        setContentView(mRoot);

        String imdbId = getIntent().getStringExtra(UtubotFilmsDeveloperPresenter.EXTRA_IMDB_ID);
        mClient = new UtubotRealDebridClient(mSettings.getFilmsAddonUrl(), mSettings.getFilmsRealDebridToken());

        mInitializer = new ExoPlayerInitializer(this);
        mController = new ExoPlayerController(this, noOpListener());
        DefaultTrackSelector trackSelector = new RestoreTrackSelector(new AdaptiveTrackSelection.Factory());
        mController.setTrackSelector(trackSelector);
        SimpleExoPlayer player = mInitializer.createPlayer(this, new CustomOverridesRenderersFactory(this), trackSelector);
        mPlayer = player;
        player.addAnalyticsListener(new FormatLogger());
        mController.setPlayer(player);
        playerView.setPlayer(player);

        PlaybackPresenter presenter = PlaybackPresenter.instance(this);
        mPlayback = engineAsPlaybackView();
        presenter.setView(mPlayback);
        mVideo = new Video();
        mVideo.videoId = imdbId != null ? imdbId : "";
        holdVideo(presenter, mVideo);
        mSponsorController = presenter.getController(SponsorBlockController.class);

        mProgress = new UtubotFilmsProgress(this);
        String type = getIntent().getStringExtra(EXTRA_TYPE);
        mStreamType = type == null ? UtubotRealDebridClient.TYPE_MOVIE : type;
        String direct = getIntent().getStringExtra(EXTRA_STREAM_URL);

        loadStreams(imdbId == null ? "" : imdbId);

        if (direct != null && !direct.isEmpty()) {
            String name = getIntent().getStringExtra(EXTRA_STREAM_NAME);
            playStream(new Stream(name == null ? "" : name, direct, 0, 0), getIntent().getLongExtra(EXTRA_START_MS, 0));
        }
    }

    private void buildPanel() {
        mPanel = new LinearLayout(this);
        mPanel.setOrientation(LinearLayout.VERTICAL);
        mPanel.setBackgroundColor(0xAA000000);
        mPanel.setPadding(ROW_PADDING, ROW_PADDING, ROW_PADDING, ROW_PADDING);
        FrameLayout.LayoutParams panelParams = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
        panelParams.height = (int) (0.45f * getResources().getDisplayMetrics().heightPixels);
        mRoot.addView(mPanel, panelParams);

        mList = new LinearLayout(this);
        mList.setOrientation(LinearLayout.VERTICAL);
        mList.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        mPanel.addView(mList);

        mStatus = new TextView(this);
        mStatus.setTextColor(Color.WHITE);
        mStatus.setTextSize(TEXT_SP);
        mStatus.setPadding(ROW_PADDING, ROW_PADDING, ROW_PADDING, ROW_PADDING);
        mRoot.addView(mStatus, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP));
    }

    private void loadStreams(String imdbId) {
        if (imdbId.isEmpty()) {
            setStatus(getString(R.string.utubot_films_missing));
            return;
        }

        setStatus("Loading streams…");
        mLoaded = false;
        clearList();

        mLoadAction = Observable.fromCallable(() -> mClient.streams(mStreamType, imdbId))
                .subscribeOn(Schedulers.io())
                .subscribe(list -> mHandler.post(() -> onStreamsLoaded(list)),
                        error -> mHandler.post(() -> setStatus(getString(R.string.utubot_films_failed, error.getMessage()))));
    }

    private void onStreamsLoaded(List<Stream> streams) {
        mStreams = UtubotRealDebridClient.sortedFor(streams, mDevice);
        streams = mStreams;
        mLoaded = true;

        if (streams.isEmpty()) {
            setStatus(getString(R.string.utubot_films_no_streams));
            return;
        }

        for (final Stream stream : streams) {
            final int position = mRows.size();
            TextView row = new TextView(this);
            row.setText(rowText(stream));
            row.setTextColor(Color.WHITE);
            row.setTextSize(TEXT_SP - 1);
            row.setPadding(ROW_PADDING, 12, ROW_PADDING, 12);
            row.setFocusable(true);
            row.setFocusableInTouchMode(true);
            row.setId(position);
            row.setOnClickListener(v -> play(position));
            mRows.add(row);
            mList.addView(row);
        }

        setFocus(0);
        setStatus(getString(R.string.utubot_films_hint, streams.size()));
    }

    private void clearList() {
        mList.removeAllViews();
        mRows.clear();
        mFocusedIndex = -1;
    }

    private void setFocus(int index) {
        if (index < 0 || index >= mRows.size()) {
            mFocusedIndex = -1;
            return;
        }

        if (mFocusedIndex >= 0 && mFocusedIndex < mRows.size()) {
            mRows.get(mFocusedIndex).setBackgroundColor(0x00000000);
        }

        mFocusedIndex = index;
        mRows.get(index).setBackgroundColor(0xAA4B3FE0);
        mRows.get(index).requestFocus();
    }

    private void play(int index) {
        if (index < 0 || index >= mStreams.size()) {
            return;
        }

        playStream(mStreams.get(index), mProgress.get(mVideo.videoId) == null ? 0 : mProgress.get(mVideo.videoId).resumeMs());
    }

    private void playStream(Stream stream, long startMs) {
        String url = stream.url;
        Log.i(TAG, "Chosen stream: " + stream.format.describe() + " verdict=" + stream.format.verdict(mDevice) + " resolution=" + stream.resolution);

        dispatchNewVideo();
        mController.setVideo(mVideo);

        String skips = getIntent().getStringExtra(UtubotFilmsDeveloperPresenter.EXTRA_SKIPS);

        if (skips != null && !skips.isEmpty() && mSponsorController != null) {
            enableSponsorBlockForSkips();
            mSponsorController.applyHandWrittenSkips(UtubotRealDebridSkips.parse(skips));
        }

        mController.openProgressiveUrl(url);

        if (startMs > 0) {
            mPlayer.seekTo(startMs);
        }

        mController.setPlayWhenReady(true);
        mHandler.removeCallbacks(mSaveTick);
        mHandler.postDelayed(mSaveTick, SAVE_INTERVAL_MS);
        mPlaying = true;
        setOverlayVisible(false);
        Log.i(TAG, "Playing: " + stream.display());
    }

    /** Remembers where the owner is, for Resume, the watched mark and Continue watching */
    private void saveProgress() {
        long duration = mPlayer == null ? C.TIME_UNSET : mPlayer.getDuration();

        if (!mPlaying || duration == C.TIME_UNSET || duration <= 0) {
            return;
        }

        Intent intent = getIntent();
        String titleId = intent.getStringExtra(EXTRA_TITLE_ID);
        mProgress.save(mVideo.videoId, mStreamType, titleId == null ? mVideo.videoId : titleId, intent.getStringExtra(EXTRA_NAME),
                intent.getStringExtra(EXTRA_POSTER), intent.getIntExtra(EXTRA_SEASON, 0), intent.getIntExtra(EXTRA_EPISODE, 0),
                mPlayer.getCurrentPosition(), duration, System.currentTimeMillis());
    }

    @Override
    protected void onPause() {
        saveProgress();
        super.onPause();
    }

    private String rowText(Stream stream) {
        StringBuilder text = new StringBuilder("  ");
        List<String> chips = stream.format.chips();

        if (stream.resolution > 0) {
            chips.add(0, stream.resolution == 2160 ? "4K" : stream.resolution + "p");
        }

        for (String chip : chips) {
            text.append('[').append(chip).append("] ");
        }

        if (stream.sizeBytes > 0) {
            text.append(Stream.formatSize(stream.sizeBytes));
        }

        String note = stream.format.note(mDevice);

        if (!note.isEmpty()) {
            text.append("   ! ").append(note);
        }

        return text.toString().trim().isEmpty() ? stream.display() : text.toString();
    }

    private void setOverlayVisible(boolean visible) {
        mPanel.setVisibility(visible ? View.VISIBLE : View.GONE);
        mStatus.setVisibility(visible ? View.VISIBLE : View.GONE);
    }

    private boolean isOverlayVisible() {
        return mPanel.getVisibility() == View.VISIBLE;
    }

    /**
     * Logs the video format the player really opened and the decoder it uses, so a wrong picture can be traced to the stream or to the TV.
     */
    private final class FormatLogger implements AnalyticsListener {
        @Override
        public void onDecoderInitialized(EventTime eventTime, int trackType, String decoderName, long initializationDurationMs) {
            if (trackType == C.TRACK_TYPE_VIDEO) {
                Log.i(TAG, "Video decoder: " + decoderName);
            }
        }

        @Override
        public void onDecoderInputFormatChanged(EventTime eventTime, int trackType, Format format) {
            if (trackType == C.TRACK_TYPE_VIDEO) {
                ColorInfo color = format.colorInfo;
                Log.i(TAG, "Video format: mime=" + format.sampleMimeType + " codecs=" + format.codecs + " size=" + format.width + "x" + format.height
                        + " colorSpace=" + (color == null ? "unset" : color.colorSpace) + " colorTransfer=" + (color == null ? "unset" : color.colorTransfer)
                        + " colorRange=" + (color == null ? "unset" : color.colorRange));
            }
        }
    }

    private void enableSponsorBlockForSkips() {
        SponsorBlockData data = SponsorBlockData.instance(this);
        data.setSponsorBlockEnabled(true);
        data.setAction(UtubotRealDebridSkips.CATEGORY, SponsorBlockData.ACTION_SKIP_ONLY);
    }

    private void dispatchNewVideo() {
        PlayerEventListener[] controllers = {mSponsorController};

        for (PlayerEventListener controller : controllers) {
            if (controller != null) {
                controller.onInit();
                controller.onNewVideo(mVideo);
                controller.onEngineInitialized();
                controller.onVideoLoaded(mVideo);
            }
        }
    }

    private void setStatus(String text) {
        mStatus.setText(text);
        Log.i(TAG, text); // a status never holds an address or a token
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        UtubotFilmsKeys.Result back = UtubotFilmsKeys.resolveBack(keyCode, event.getAction(), event.getRepeatCount(), isOverlayVisible(), mPlaying);

        if (back == UtubotFilmsKeys.Result.HIDE_OVERLAY) {
            setOverlayVisible(false);
            return true;
        } else if (back == UtubotFilmsKeys.Result.LEAVE) {
            finish();
            return true;
        } else if (back == UtubotFilmsKeys.Result.CONSUME) {
            return true;
        }

        if (mPlaying && !isOverlayVisible() && (UtubotKeys.actsOnFocus(keyCode) || keyCode == KeyEvent.KEYCODE_MENU)) {
            setOverlayVisible(true);
            setFocus(Math.max(mFocusedIndex, 0));
            return true;
        }

        if (mLoaded && !mRows.isEmpty()) {
            if (keyCode == KeyEvent.KEYCODE_DPAD_UP) {
                setFocus(mFocusedIndex - 1);
                return true;
            }

            if (keyCode == KeyEvent.KEYCODE_DPAD_DOWN) {
                setFocus(mFocusedIndex + 1);
                return true;
            }

            if (keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER) {
                if (mFocusedIndex >= 0 && mFocusedIndex < mStreams.size()) {
                    play(mFocusedIndex);
                    return true;
                }
            }
        }

        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (UtubotKeys.isBackKey(keyCode)) {
            return true; // the press decided; the default would call onBackPressed
        }

        return super.onKeyUp(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        if (mRoot == null) {
            super.onDestroy();
            return;
        }

        mHandler.removeCallbacks(mSaveTick);
        RxHelper.disposeActions(mLoadAction);

        if (mSponsorController != null) {
            mSponsorController.applyHandWrittenSkips(null);
        }

        if (mController != null) {
            mController.release();
        }

        if (mInitializer != null) {
            mInitializer.release();
        }

        super.onDestroy();
    }

    /**
     * The engine behind a {@link PlaybackView}: what the engine does is answered by it, what a playback screen would do is a no-op.
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

    private static void holdVideo(PlaybackPresenter presenter, Video video) {
        try {
            Field field = PlaybackPresenter.class.getDeclaredField("mVideo");
            field.setAccessible(true);
            field.set(presenter, new WeakReference<>(video));
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Cannot hold the video of the harness", e);
        }
    }

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
