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
import android.widget.LinearLayout;
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
import com.liskovsoft.smartyoutubetv2.common.prefs.SponsorBlockData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient;
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
 * Debug builds only. The hidden developer entry of the Real-Debrid spike: paste (or start from the intent) a Stremio stream addon
 * address and an IMDb id, list the streams the addon returns, and play one through the app's real player on the progressive path (a muxed
 * MP4/MKV, an HDR/Dolvision/AV1 file, whatever the extractor decodes), next to {@link ExoPlayerController#openUrlList}. A hand-written skip
 * list, when given, is fed through the sponsor block so cut-style playback is proven without building a director's cut.
 *
 * <p>Nothing here reaches YouTube; the addon and the stream are the developer's own (a self-hosted Comet, a Torrentio instance, the owner's
 * Real-Debrid links). The Real-Debrid token is passed in and added to a stream's address by {@link UtubotRealDebridClient}, never logged.
 *
 * <pre>
 * adb shell am start -n dev.utubot.tv/com.liskovsoft.smartyoutubetv2.tv.utubot.harness.RealDebridHarnessActivity \
 *     --es imdb_id tt0944947 --es addon_url https://torrentio.strem.io --es rd_token "" --es skips "30,90;600,720"
 * </pre>
 */
public class RealDebridHarnessActivity extends Activity {
    private static final String TAG = "UtubotRealDebridHarness";
    private static final String EXTRA_IMDB_ID = "imdb_id";
    private static final String EXTRA_ADDON_URL = "addon_url";
    private static final String EXTRA_RD_TOKEN = "rd_token";
    private static final String EXTRA_SKIPS = "skips";

    private static final int TEXT_SP = 18;
    private static final int ROW_PADDING = 16;

    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private FrameLayout mRoot;
    private LinearLayout mPanel;
    private TextView mAddonField;
    private TextView mImdbField;
    private TextView mLoadButton;
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

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        mRoot = new FrameLayout(this);
        mRoot.setBackgroundColor(Color.BLACK);
        PlayerView playerView = new PlayerView(this);
        playerView.setUseController(false);
        mRoot.addView(playerView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        buildPanel();
        setContentView(mRoot);

        String addonUrl = getIntent().getStringExtra(EXTRA_ADDON_URL);
        String imdbId = getIntent().getStringExtra(EXTRA_IMDB_ID);
        String rdToken = getIntent().getStringExtra(EXTRA_RD_TOKEN);
        String skips = getIntent().getStringExtra(EXTRA_SKIPS);

        if (addonUrl != null) {
            mAddonField.setText(addonUrl);
        }

        if (imdbId != null) {
            mImdbField.setText(imdbId);
        }

        mClient = new UtubotRealDebridClient(addonUrl == null ? "" : addonUrl, rdToken);

        mInitializer = new ExoPlayerInitializer(this);
        mController = new ExoPlayerController(this, noOpListener());
        DefaultTrackSelector trackSelector = new RestoreTrackSelector(new AdaptiveTrackSelection.Factory());
        mController.setTrackSelector(trackSelector);
        SimpleExoPlayer player = mInitializer.createPlayer(this, new CustomOverridesRenderersFactory(this), trackSelector);
        mController.setPlayer(player);
        playerView.setPlayer(player);

        PlaybackPresenter presenter = PlaybackPresenter.instance(this);
        mPlayback = engineAsPlaybackView();
        presenter.setView(mPlayback);
        mVideo = new Video();
        mVideo.videoId = imdbId != null ? imdbId : "";
        holdVideo(presenter, mVideo);
        mSponsorController = presenter.getController(SponsorBlockController.class);

        if (imdbId != null && !imdbId.isEmpty()) {
            loadStreams(addonUrl == null ? "" : addonUrl, imdbId, skips);
        } else {
            setStatus("Enter the addon address and the IMDb id, then Load.");
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

        mAddonField = editableLabel("Addon: ", "");
        mImdbField = editableLabel("IMDb: ", "");
        mLoadButton = button("Load streams");
        mPanel.addView(mAddonField);
        mPanel.addView(mImdbField);
        mPanel.addView(mLoadButton);

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

    private TextView editableLabel(String prefix, String value) {
        TextView view = new TextView(this);
        view.setText(prefix + value);
        view.setTextColor(Color.WHITE);
        view.setTextSize(TEXT_SP);
        view.setPadding(ROW_PADDING, 8, ROW_PADDING, 8);
        view.setFocusable(true);
        view.setFocusableInTouchMode(true);
        return view;
    }

    private TextView button(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(Color.GREEN);
        view.setBackgroundColor(0xAA000000);
        view.setTextSize(TEXT_SP);
        view.setPadding(ROW_PADDING, 12, ROW_PADDING, 12);
        view.setFocusable(true);
        view.setFocusableInTouchMode(true);
        view.setOnClickListener(v -> loadStreams(mAddonField.getText().toString().trim(), mImdbField.getText().toString().trim(), null));
        return view;
    }

    private void loadStreams(String addonUrl, String imdbId, @Nullable String skips) {
        if (addonUrl.isEmpty() || imdbId.isEmpty()) {
            setStatus("Add the addon address and the IMDb id first.");
            return;
        }

        mClient = new UtubotRealDebridClient(addonUrl, getIntent().getStringExtra(EXTRA_RD_TOKEN));
        setStatus("Loading streams…");
        mLoaded = false;
        clearList();

        mLoadAction = Observable.fromCallable(() -> mClient.streams(imdbId))
                .subscribeOn(Schedulers.io())
                .subscribe(list -> mHandler.post(() -> onStreamsLoaded(list, skips)),
                        error -> mHandler.post(() -> setStatus("Can't load streams: " + error.getMessage())));
    }

    private void onStreamsLoaded(List<Stream> streams, @Nullable String skips) {
        mStreams = streams;
        mLoaded = true;

        if (streams.isEmpty()) {
            setStatus("The addon returned no playable streams.");
            return;
        }

        for (final Stream stream : streams) {
            final int position = mRows.size();
            TextView row = new TextView(this);
            row.setText("  " + stream.display());
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
        setStatus(streams.size() + " stream(s). Move and press OK to play" + (skips != null ? ", skips on." : "."));
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

        Stream stream = mStreams.get(index);
        String url = mClient.playbackUrl(stream);

        if (url == null) {
            setStatus("No address to play this stream (Real-Debrid token needed?).");
            return;
        }

        dispatchNewVideo();
        mController.setVideo(mVideo);

        String skips = getIntent().getStringExtra(EXTRA_SKIPS);

        if (skips != null && !skips.isEmpty() && mSponsorController != null) {
            enableSponsorBlockForSkips();
            mSponsorController.applyHandWrittenSkips(UtubotRealDebridSkips.parse(skips));
        }

        mController.openProgressiveUrl(url);
        mController.setPlayWhenReady(true);
        setStatus("Playing: " + url);
        Log.i(TAG, "play " + stream.display() + " -> " + url);
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
        Log.i(TAG, text);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
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
    protected void onDestroy() {
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
