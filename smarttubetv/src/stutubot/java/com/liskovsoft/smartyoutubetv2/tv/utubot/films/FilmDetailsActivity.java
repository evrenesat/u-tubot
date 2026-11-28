package com.liskovsoft.smartyoutubetv2.tv.utubot.films;

import android.app.Activity;
import android.content.Intent;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.bumptech.glide.Glide;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmDevice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Episode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Item;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsDeveloperPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress.Entry;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmPlay;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotMenu;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient.Stream;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * One film or series: backdrop, poster, year, runtime, rating, plot, a big Play (or Resume) button and the stream picker (quality, size,
 * HDR and Dolby Vision, audio and source as chips, best stream first). A series adds the season and episode pickers. Back goes to the list.
 */
public class FilmDetailsActivity extends Activity {
    static final String EXTRA_TYPE = "type";
    static final String EXTRA_ID = "id";
    static final String EXTRA_NAME = "name";
    static final String EXTRA_POSTER = "poster";
    private static final String TAG = "UtubotFilmDetails";
    private static final int BACKDROP_ALPHA = 90;
    private static final int PLOT_LINES = 4;
    private static final int EPISODE_W = 160;

    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService mIo = Executors.newFixedThreadPool(2);
    private UtubotFilmsProgress mProgress;
    private UtubotFilmDevice mDevice;
    private UtubotSettings mSettings;
    private String mType;
    private String mId;
    private String mName;
    private String mPoster;
    private Item mItem;
    private int mSeason = 1;
    private boolean mFocusEpisode; // the first view of a series: focus the current or next episode, not the first
    private View mSelectedEpisodeCard;
    private Episode mEpisode;
    private List<Stream> mStreams = new ArrayList<>();
    private LinearLayout mContent;
    private LinearLayout mEpisodeSlot;
    private LinearLayout mSeasonSlot;
    private LinearLayout mStreamList;
    private TextView mStreamStatus;
    private TextView mPlay;
    private TextView mCuts;
    private ImageView mBackdrop;
    private boolean mDestroyed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        mSettings = UtubotSettings.instance(this);

        if (!mSettings.isFilmsDeveloperEnabled()) {
            finish();
            return;
        }

        mType = getIntent().getStringExtra(EXTRA_TYPE);
        mId = getIntent().getStringExtra(EXTRA_ID);
        mName = getIntent().getStringExtra(EXTRA_NAME);
        mPoster = getIntent().getStringExtra(EXTRA_POSTER);
        mProgress = new UtubotFilmsProgress(this);
        mDevice = new UtubotFilmDevice(this);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(FilmsUi.BACKGROUND);
        mBackdrop = new ImageView(this);
        mBackdrop.setScaleType(ImageView.ScaleType.CENTER_CROP);
        mBackdrop.setImageAlpha(BACKDROP_ALPHA);
        root.addView(mBackdrop, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        View scrim = new View(this);
        scrim.setBackground(new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, new int[]{FilmsUi.BACKGROUND, 0xCC181818, 0x66181818}));
        root.addView(scrim, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        ScrollView scroll = new ScrollView(this);
        mContent = new LinearLayout(this);
        mContent.setOrientation(LinearLayout.VERTICAL);
        mContent.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN), FilmsUi.dp(this, 32), FilmsUi.dp(this, FilmsUi.MARGIN), FilmsUi.dp(this, 32));
        scroll.setClipChildren(false);
        mContent.setClipChildren(false);
        mContent.setClipToPadding(false);
        scroll.addView(mContent, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(scroll, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        buildHeader(null);
        loadMeta();
    }

    private void loadMeta() {
        mIo.execute(() -> {
            try {
                Item item = new UtubotFilmsCatalog(mSettings.getFilmsCatalogUrl()).meta(mType, mId);
                mHandler.post(() -> onMeta(item));
            } catch (Exception e) {
                Log.w(TAG, "Details failed: " + e.getMessage());
                mHandler.post(this::showMetaError);
            }
        });
    }

    private void showMetaError() {
        if (mDestroyed) {
            return;
        }

        setStreamStatus("");
        mStreamList.removeAllViews();
        View error = FilmsUi.errorBlock(this, "Cannot load the details. Check the connection and try again.", v -> {
            mStreamList.removeAllViews();
            setStreamStatus("Loading...");
            loadMeta();
        });
        mStreamList.addView(error);
        FilmsUi.retryButton(error).requestFocus();
    }

    @Override
    protected void onResume() {
        super.onResume();

        if (mItem != null) {
            refreshMarks();
        }
    }

    private void onMeta(Item item) {
        if (mDestroyed) {
            return;
        }

        mItem = item;
        mContent.removeAllViews();
        buildHeader(item);

        if (!item.background.isEmpty()) {
            Glide.with(getApplicationContext()).load(item.background).into(mBackdrop);
        }

        if (item.isSeries()) {
            mProgress.rememberEpisodes(item.id, item.episodes);
            Episode resume = resumeEpisode(item);
            mEpisode = resume != null ? resume : UtubotFilmsCatalog.firstUnwatched(item.episodes, System.currentTimeMillis(), this::isWatched);
            mFocusEpisode = true;
            mSeason = mEpisode != null ? mEpisode.season : 1;
            buildEpisodePickers();
        }

        loadStreams();
    }

    private void buildHeader(Item item) {
        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setClipChildren(false);

        ImageView poster = new ImageView(this);
        poster.setScaleType(ImageView.ScaleType.CENTER_CROP);
        poster.setBackground(FilmsUi.rounded(this, FilmsUi.CARD, android.graphics.Color.TRANSPARENT, 0));
        String posterUrl = item != null && !item.poster.isEmpty() ? item.poster : mPoster;

        if (posterUrl != null && !posterUrl.isEmpty()) {
            Glide.with(getApplicationContext()).load(posterUrl).into(poster);
        }

        top.addView(poster, new LinearLayout.LayoutParams(FilmsUi.dp(this, 180), FilmsUi.dp(this, 270)));

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(FilmsUi.dp(this, 28), 0, 0, 0);
        info.setClipChildren(false);
        info.setClipToPadding(false);
        info.addView(FilmsUi.text(this, item != null ? item.name : mName == null ? "" : mName, 30, FilmsUi.TEXT, true));

        if (item != null) {
            TextView facts = FilmsUi.text(this, item.facts(), FilmsUi.BODY_SP, FilmsUi.TEXT_DIM, false);
            facts.setPadding(0, FilmsUi.dp(this, 4), 0, FilmsUi.dp(this, 10));
            info.addView(facts);

            TextView plot = FilmsUi.text(this, item.plot, FilmsUi.BODY_SP, FilmsUi.TEXT, false);
            plot.setMaxLines(PLOT_LINES);
            plot.setEllipsize(TextUtils.TruncateAt.END);
            plot.setLineSpacing(0, 1.1f);
            info.addView(plot, new LinearLayout.LayoutParams(FilmsUi.dp(this, 640), ViewGroup.LayoutParams.WRAP_CONTENT));
        }

        mPlay = FilmsUi.button(this, "Loading...", 22, v -> playBest());
        mPlay.setPadding(FilmsUi.dp(this, 28), FilmsUi.dp(this, 10), FilmsUi.dp(this, 28), FilmsUi.dp(this, 10));
        mPlay.setEnabled(false);
        LinearLayout.LayoutParams playParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        playParams.topMargin = FilmsUi.dp(this, 16);
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.addView(mPlay);
        mCuts = FilmsUi.button(this, "✂  Cuts", 22, v -> openCuts());
        mCuts.setPadding(FilmsUi.dp(this, 28), FilmsUi.dp(this, 10), FilmsUi.dp(this, 28), FilmsUi.dp(this, 10));
        mCuts.setEnabled(false);
        LinearLayout.LayoutParams cutsParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cutsParams.leftMargin = FilmsUi.dp(this, 16);
        actions.addView(mCuts, cutsParams);
        info.addView(actions, playParams);
        top.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        mContent.addView(top);

        mSeasonSlot = new LinearLayout(this);
        mSeasonSlot.setOrientation(LinearLayout.VERTICAL);
        mContent.addView(mSeasonSlot);
        mEpisodeSlot = new LinearLayout(this);
        mEpisodeSlot.setOrientation(LinearLayout.VERTICAL);
        mContent.addView(mEpisodeSlot);

        // A film has no pickers, so its streams sit beside the poster, under the Play button; a series lists them below the episodes
        LinearLayout streamHost = UtubotRealDebridClient.TYPE_SERIES.equals(mType) ? mContent : info;
        TextView header = FilmsUi.text(this, "Streams", FilmsUi.ROW_HEADER_SP, FilmsUi.TEXT, false);
        header.setPadding(0, FilmsUi.dp(this, 14), 0, FilmsUi.dp(this, 6));
        streamHost.addView(header);
        mStreamStatus = FilmsUi.text(this, item == null ? "Loading..." : "", FilmsUi.BODY_SP, FilmsUi.WARN, false);
        mStreamStatus.setVisibility(item == null ? View.VISIBLE : View.GONE);
        streamHost.addView(mStreamStatus);
        mStreamList = new LinearLayout(this);
        mStreamList.setOrientation(LinearLayout.VERTICAL);
        streamHost.addView(mStreamList, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private void setStreamStatus(String text) {
        mStreamStatus.setText(text);
        mStreamStatus.setVisibility(text.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void buildEpisodePickers() {
        mSeasonSlot.removeAllViews();
        mEpisodeSlot.removeAllViews();
        List<Integer> seasons = UtubotFilmsCatalog.seasons(mItem.episodes);

        if (seasons.isEmpty()) {
            return;
        }

                LinearLayout seasonRow = new LinearLayout(this);
        seasonRow.setClipChildren(false);
        seasonRow.setPadding(FilmsUi.dp(this, 4), FilmsUi.dp(this, 14), 0, 0);

        for (int season : seasons) {
            TextView button = FilmsUi.button(this, "Season " + season, FilmsUi.BODY_SP, v -> selectSeason(season));
            button.setBackground(FilmsUi.rounded(this, season == mSeason ? FilmsUi.ACCENT : FilmsUi.CARD, android.graphics.Color.TRANSPARENT, 3));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            params.setMargins(FilmsUi.dp(this, 4), FilmsUi.dp(this, 4), FilmsUi.dp(this, 8), FilmsUi.dp(this, 4));
            seasonRow.addView(button, params);
            FilmsUi.focusRing(button, button, season == mSeason ? FilmsUi.ACCENT : FilmsUi.CARD, null);
        }

        HorizontalScrollView seasonScroll = new HorizontalScrollView(this);
        seasonScroll.setHorizontalScrollBarEnabled(false);
        seasonScroll.addView(seasonRow);
        mSeasonSlot.addView(seasonScroll);

        TextView episodeHeader = FilmsUi.text(this, "Episodes", FilmsUi.ROW_HEADER_SP, FilmsUi.TEXT, false);
        episodeHeader.setPadding(0, FilmsUi.dp(this, 10), 0, FilmsUi.dp(this, 4));
        mEpisodeSlot.addView(episodeHeader);
        LinearLayout row = new LinearLayout(this);
        row.setClipChildren(false);
        row.setPadding(FilmsUi.dp(this, 8), 0, 0, 0);

        for (Episode episode : UtubotFilmsCatalog.episodesOf(mItem.episodes, mSeason)) {
            Entry entry = mProgress.get(episode.videoId(mItem.id));
            boolean watched = entry != null && entry.isWatched();
            View card = episodeCard(episode, entry == null ? 0f : entry.share(), watched);
            row.addView(card);

            if (mEpisode != null && mEpisode.season == episode.season && mEpisode.number == episode.number) {
                mSelectedEpisodeCard = card;
            }
        }

        HorizontalScrollView episodeScroll = new HorizontalScrollView(this);
        episodeScroll.setHorizontalScrollBarEnabled(false);
        episodeScroll.setClipToPadding(false);
        episodeScroll.addView(row);
        mEpisodeSlot.addView(episodeScroll);
        showSelectedEpisode(episodeScroll);
    }

    /** The selected episode is the first card in view; on the first view of the screen it also has the focus */
    private void showSelectedEpisode(HorizontalScrollView scroll) {
        View card = mSelectedEpisodeCard;
        boolean focus = mFocusEpisode;
        mSelectedEpisodeCard = null;

        if (card == null) {
            return;
        }

        scroll.post(() -> {
            scroll.scrollTo(Math.max(0, card.getLeft() - FilmsUi.dp(this, 8)), 0);

            if (focus) {
                card.requestFocus();
            }
        });
    }

    private boolean isWatched(Episode episode) {
        Entry entry = mProgress.get(episode.videoId(mItem.id));

        return entry != null && entry.isWatched();
    }

    private View episodeCard(Episode episode, float share, boolean watched) {
        FrameLayout card = new FrameLayout(this);
        boolean selected = mEpisode != null && mEpisode.season == episode.season && mEpisode.number == episode.number;
        int textColor = selected ? FilmsUi.TEXT : FilmsUi.TEXT_DIM;
        LinearLayout texts = new LinearLayout(this);
        texts.setOrientation(LinearLayout.VERTICAL);
        texts.setGravity(android.view.Gravity.CENTER_VERTICAL);
        int pad = FilmsUi.dp(this, 12);
        texts.setPadding(pad, pad, pad, pad);
        texts.addView(FilmsUi.text(this, "E" + episode.number + (watched ? "  \u2713" : ""), FilmsUi.BODY_SP, FilmsUi.TEXT, true));
        String shortTitle = episode.shortTitle();

        if (!shortTitle.isEmpty()) {
            TextView title = FilmsUi.text(this, shortTitle, FilmsUi.CHIP_SP, selected ? FilmsUi.TEXT : textColor, false);
            title.setMaxLines(2);
            title.setEllipsize(TextUtils.TruncateAt.END);
            texts.addView(title);
        }

        card.addView(texts, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        if (share > 0 && !watched) {
            View bar = new View(this);
            bar.setBackgroundColor(FilmsUi.TEXT);
            card.addView(bar, new FrameLayout.LayoutParams(Math.round(FilmsUi.dp(this, EPISODE_W) * share), FilmsUi.dp(this, 4),
                    android.view.Gravity.BOTTOM | android.view.Gravity.START));
        }

        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(FilmsUi.dp(this, EPISODE_W), FilmsUi.dp(this, 92));
        params.setMargins(FilmsUi.dp(this, 4), FilmsUi.dp(this, 8), FilmsUi.dp(this, 8), FilmsUi.dp(this, 8));
        card.setLayoutParams(params);
        FilmsUi.clipRounded(card);
        FilmsUi.focusRing(card, card, selected ? FilmsUi.ACCENT : FilmsUi.CARD, null);
        card.setOnClickListener(v -> selectEpisode(episode));

        return card;
    }

    private void selectSeason(int season) {
        mFocusEpisode = false;
        mSeason = season;
        List<Episode> episodes = UtubotFilmsCatalog.episodesOf(mItem.episodes, season);
        mEpisode = episodes.isEmpty() ? null : episodes.get(0);
        buildEpisodePickers();
        loadStreams();
    }

    private void selectEpisode(Episode episode) {
        mFocusEpisode = false;
        mEpisode = episode;
        buildEpisodePickers();
        loadStreams();
    }

    private void refreshMarks() {
        if (mItem.isSeries()) {
            buildEpisodePickers();
        }

        updatePlayLabel();
    }

    private String videoId() {
        return mItem.isSeries() ? (mEpisode == null ? mItem.id : mEpisode.videoId(mItem.id)) : mItem.id;
    }

    private Episode resumeEpisode(Item item) {
        UtubotFilmsProgress.Row latest = null;

        for (UtubotFilmsProgress.Row row : mProgress.continueRow(System.currentTimeMillis())) {
            if (item.id.equals(row.titleId)) {
                latest = row;
                break;
            }
        }

        if (latest == null) {
            return null;
        }

        for (Episode episode : item.episodes) {
            if (episode.season == latest.season && episode.number == latest.episode) {
                return episode;
            }
        }

        return null;
    }

    private void loadStreams() {
        mStreams = new ArrayList<>();
        mStreamList.removeAllViews();
        mPlay.setEnabled(false);
        mPlay.setText("Loading...");
        String videoId = videoId();

        if (mSettings.getFilmsAddonUrl().isEmpty()) {
            setStreamStatus(getString(R.string.utubot_films_no_addon));
            mPlay.setText("No stream addon");
            return;
        }

        setStreamStatus("");

        for (int i = 0; i < FilmsUi.PLACEHOLDER_ROWS; i++) {
            View bar = FilmsUi.placeholderBar(this, 560, 34, i == 0 ? 3 : 6);
            mStreamList.addView(bar);
        }

        mIo.execute(() -> {
            try {
                UtubotRealDebridClient client = new UtubotRealDebridClient(mSettings.getFilmsAddonUrl(), mSettings.getFilmsRealDebridToken());
                List<Stream> streams = UtubotRealDebridClient.sortedFor(client.streams(mItem.isSeries() ? UtubotRealDebridClient.TYPE_SERIES
                        : UtubotRealDebridClient.TYPE_MOVIE, videoId), mDevice);
                mHandler.post(() -> {
                    if (!mDestroyed && videoId.equals(videoId())) {
                        onStreams(streams);
                    }
                });
            } catch (Exception e) {
                Log.w(TAG, "Streams failed: " + e.getMessage());
                mHandler.post(() -> {
                    if (mDestroyed || !videoId.equals(videoId())) {
                        return;
                    }

                    mStreamList.removeAllViews();
                    setStreamStatus("");
                    mPlay.setText("No streams");
                    View error = FilmsUi.errorBlock(this, "Cannot load streams. Check the connection and try again.", v -> loadStreams());
                    mStreamList.addView(error);
                    FilmsUi.retryButton(error).requestFocus();
                });
            }
        });
    }

    private void onStreams(List<Stream> streams) {
        mStreams = streams;
        mStreamList.removeAllViews();
        setStreamStatus(streams.isEmpty() ? "The addon returned no playable streams." : "");
        mPlay.setEnabled(!streams.isEmpty());
        mCuts.setEnabled(!streams.isEmpty());
        updatePlayLabel();

        for (int i = 0; i < streams.size(); i++) {
            Stream stream = streams.get(i);
            mStreamList.addView(FilmsUi.streamRow(this, stream, i == 0, mDevice, v -> play(stream)));
        }

        if (!streams.isEmpty() && !mFocusEpisode) {
            mPlay.requestFocus();
        }
    }

    private void updatePlayLabel() {
        if (mStreams.isEmpty() || mItem == null) {
            return;
        }

        Entry entry = mProgress.get(videoId());
        boolean resume = entry != null && entry.resumeMs() > 0;
        String episode = mItem.isSeries() && mEpisode != null ? "S" + mEpisode.season + " E" + mEpisode.number + "  " : "";
        mPlay.setText("▶  " + (resume ? "Resume " + episode + FilmsUi.clock(entry.resumeMs()) : "Play " + episode).trim());
    }

    private void playBest() {
        if (!mStreams.isEmpty()) {
            play(mStreams.get(0));
        }
    }

    private void play(Stream stream) {
        UtubotFilmPlay film = newFilm(stream);
        Log.i(TAG, "Chosen stream: " + stream.format.describe() + " verdict=" + stream.format.verdict(mDevice) + " resolution=" + stream.resolution);
        com.liskovsoft.smartyoutubetv2.common.app.views.ViewManager.instance(this).setFilmParent(getClass()); // Back from the player lands here
        PlaybackPresenter.instance(this).openVideo(Video.fromFilm(film));
    }

    private UtubotFilmPlay newFilm(Stream stream) {
        String videoId = videoId();
        Entry entry = mProgress.get(videoId);
        UtubotFilmPlay film = new UtubotFilmPlay(videoId, mItem.isSeries() ? UtubotRealDebridClient.TYPE_SERIES : UtubotRealDebridClient.TYPE_MOVIE,
                mItem.id, mItem.name, mItem.poster, mItem.isSeries() && mEpisode != null ? mEpisode.season : 0,
                mItem.isSeries() && mEpisode != null ? mEpisode.number : 0, stream.url, stream.name, entry == null ? 0L : entry.resumeMs(),
                stream.sizeBytes);
        film.setCatalogue(mItem.year, mItem.isSeries() && mEpisode != null ? mEpisode.shortTitle() : "");

        return film;
    }

    /**
     * The cut picker of the best stream, before anything plays: a ready cut starts the film with it. The length the backend builds a cut
     * for is the one the player saw last for this title, else the runtime the catalogue lists (the cut then applies within the film
     * tolerance).
     */
    private void openCuts() {
        if (mStreams.isEmpty() || mItem == null) {
            return;
        }

        UtubotFilmPlay film = newFilm(mStreams.get(0));
        Entry entry = mProgress.get(videoId());
        film.setReleaseDurationMs(entry != null && entry.durationMs > 0 ? entry.durationMs : UtubotFilmsCatalog.runtimeMs(mItem.runtime));
        UtubotMenu.showCuts(this, Video.fromFilm(film));
    }

    @Override
    protected void onDestroy() {
        mDestroyed = true;
        mIo.shutdownNow();
        super.onDestroy();
    }
}
