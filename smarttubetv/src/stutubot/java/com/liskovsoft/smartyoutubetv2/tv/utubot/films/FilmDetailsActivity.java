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
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmDevice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Episode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Item;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsDeveloperPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress.Entry;
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
    private Episode mEpisode;
    private List<Stream> mStreams = new ArrayList<>();
    private LinearLayout mContent;
    private LinearLayout mEpisodeSlot;
    private LinearLayout mSeasonSlot;
    private LinearLayout mStreamList;
    private TextView mStreamStatus;
    private TextView mPlay;
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
        scroll.addView(mContent, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(scroll, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        buildHeader(null);
        mIo.execute(() -> {
            try {
                Item item = new UtubotFilmsCatalog(mSettings.getFilmsCatalogUrl()).meta(mType, mId);
                mHandler.post(() -> onMeta(item));
            } catch (Exception e) {
                Log.w(TAG, "Details failed: " + e.getMessage());
                mHandler.post(() -> mStreamStatus.setText("Cannot load the details: " + e.getMessage()));
            }
        });
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
            Episode resume = resumeEpisode(item);
            mEpisode = resume != null ? resume : first(item.episodes);
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
        mPlay.setEnabled(false);
        LinearLayout.LayoutParams playParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        playParams.topMargin = FilmsUi.dp(this, 16);
        info.addView(mPlay, playParams);
        top.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        mContent.addView(top);

        mSeasonSlot = new LinearLayout(this);
        mSeasonSlot.setOrientation(LinearLayout.VERTICAL);
        mContent.addView(mSeasonSlot);
        mEpisodeSlot = new LinearLayout(this);
        mEpisodeSlot.setOrientation(LinearLayout.VERTICAL);
        mContent.addView(mEpisodeSlot);

        TextView header = FilmsUi.text(this, "Streams", FilmsUi.ROW_HEADER_SP, FilmsUi.TEXT, false);
        header.setPadding(0, FilmsUi.dp(this, 20), 0, FilmsUi.dp(this, 8));
        mContent.addView(header);
        mStreamStatus = FilmsUi.text(this, item == null ? "Loading..." : "", FilmsUi.BODY_SP, FilmsUi.WARN, false);
        mContent.addView(mStreamStatus);
        mStreamList = new LinearLayout(this);
        mStreamList.setOrientation(LinearLayout.VERTICAL);
        mContent.addView(mStreamList);
    }

    private void buildEpisodePickers() {
        mSeasonSlot.removeAllViews();
        mEpisodeSlot.removeAllViews();
        List<Integer> seasons = UtubotFilmsCatalog.seasons(mItem.episodes);

        if (seasons.isEmpty()) {
            return;
        }

        TextView seasonHeader = FilmsUi.text(this, "Season", FilmsUi.ROW_HEADER_SP, FilmsUi.TEXT, false);
        seasonHeader.setPadding(0, FilmsUi.dp(this, 20), 0, FilmsUi.dp(this, 8));
        mSeasonSlot.addView(seasonHeader);
        LinearLayout seasonRow = new LinearLayout(this);
        seasonRow.setClipChildren(false);

        for (int season : seasons) {
            TextView button = FilmsUi.button(this, String.valueOf(season), FilmsUi.BODY_SP, v -> selectSeason(season));
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
        episodeHeader.setPadding(0, FilmsUi.dp(this, 12), 0, FilmsUi.dp(this, 8));
        mEpisodeSlot.addView(episodeHeader);
        LinearLayout row = new LinearLayout(this);
        row.setClipChildren(false);

        for (Episode episode : UtubotFilmsCatalog.episodesOf(mItem.episodes, mSeason)) {
            Entry entry = mProgress.get(episode.videoId(mItem.id));
            boolean watched = entry != null && entry.isWatched();
            View card = episodeCard(episode, entry == null ? 0f : entry.share(), watched);
            row.addView(card);
        }

        HorizontalScrollView episodeScroll = new HorizontalScrollView(this);
        episodeScroll.setHorizontalScrollBarEnabled(false);
        episodeScroll.setClipToPadding(false);
        episodeScroll.addView(row);
        mEpisodeSlot.addView(episodeScroll);
    }

    private View episodeCard(Episode episode, float share, boolean watched) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(android.view.Gravity.CENTER_VERTICAL);
        int pad = FilmsUi.dp(this, 12);
        card.setPadding(pad, pad, pad, pad);
        boolean selected = mEpisode != null && mEpisode.season == episode.season && mEpisode.number == episode.number;
        card.addView(FilmsUi.text(this, "E" + episode.number + (watched ? "  ✓" : ""), FilmsUi.BODY_SP, watched ? FilmsUi.WARN : FilmsUi.TEXT, true));
        TextView title = FilmsUi.text(this, episode.title, FilmsUi.CHIP_SP + 1, FilmsUi.TEXT_DIM, false);
        title.setMaxLines(2);
        title.setEllipsize(TextUtils.TruncateAt.END);
        card.addView(title);

        if (share > 0 && !watched) {
            View bar = new View(this);
            bar.setBackgroundColor(FilmsUi.WARN);
            card.addView(bar, new LinearLayout.LayoutParams(Math.round(FilmsUi.dp(this, 130) * share), FilmsUi.dp(this, 3)));
        }

        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(FilmsUi.dp(this, 154), FilmsUi.dp(this, 84));
        params.setMargins(FilmsUi.dp(this, 4), FilmsUi.dp(this, 6), FilmsUi.dp(this, 8), FilmsUi.dp(this, 6));
        card.setLayoutParams(params);
        FilmsUi.focusRing(card, card, selected ? FilmsUi.ACCENT : FilmsUi.CARD, null);
        card.setOnClickListener(v -> selectEpisode(episode));

        return card;
    }

    private void selectSeason(int season) {
        mSeason = season;
        List<Episode> episodes = UtubotFilmsCatalog.episodesOf(mItem.episodes, season);
        mEpisode = episodes.isEmpty() ? null : episodes.get(0);
        buildEpisodePickers();
        loadStreams();
    }

    private void selectEpisode(Episode episode) {
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
        Entry latest = null;

        for (Entry entry : mProgress.continueWatching()) {
            if (item.id.equals(entry.titleId)) {
                latest = entry;
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

    private static Episode first(List<Episode> episodes) {
        List<Integer> seasons = UtubotFilmsCatalog.seasons(episodes);

        return seasons.isEmpty() ? null : UtubotFilmsCatalog.episodesOf(episodes, seasons.get(0)).get(0);
    }

    private void loadStreams() {
        mStreams = new ArrayList<>();
        mStreamList.removeAllViews();
        mPlay.setEnabled(false);
        mPlay.setText("Loading...");
        String videoId = videoId();

        if (mSettings.getFilmsAddonUrl().isEmpty()) {
            mStreamStatus.setText("Set the stream addon in Settings, Updates, Films (developer).");
            mPlay.setText("No stream addon");
            return;
        }

        mStreamStatus.setText("Loading streams...");
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
                    mStreamStatus.setText("Cannot load streams: " + e.getMessage());
                    mPlay.setText("No streams");
                });
            }
        });
    }

    private void onStreams(List<Stream> streams) {
        mStreams = streams;
        mStreamList.removeAllViews();
        mStreamStatus.setText(streams.isEmpty() ? "The addon returned no playable streams." : "");
        mPlay.setEnabled(!streams.isEmpty());
        updatePlayLabel();

        for (int i = 0; i < streams.size(); i++) {
            mStreamList.addView(streamRow(streams.get(i), i == 0));
        }

        if (!streams.isEmpty()) {
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

    private View streamRow(Stream stream, boolean best) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        int pad = FilmsUi.dp(this, 10);
        row.setPadding(pad, pad, pad, pad);

        if (best) {
            TextView bestChip = FilmsUi.chip(this, "Best", false);
            bestChip.setBackground(FilmsUi.rounded(this, FilmsUi.ACCENT, android.graphics.Color.TRANSPARENT, 0));
            row.addView(bestChip);
        }

        if (stream.resolution > 0) {
            TextView quality = FilmsUi.chip(this, stream.resolution == 2160 ? "4K" : stream.resolution + "p", false);
            quality.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
            row.addView(quality);
        }

        for (String chip : stream.format.chips()) {
            row.addView(FilmsUi.chip(this, chip, false));
        }

        if (stream.sizeBytes > 0) {
            row.addView(FilmsUi.chip(this, Stream.formatSize(stream.sizeBytes), false));
        }

        String note = stream.format.note(mDevice);

        if (!note.isEmpty()) {
            row.addView(FilmsUi.chip(this, note, true));
        }

        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, FilmsUi.dp(this, 3), 0, FilmsUi.dp(this, 3));
        row.setLayoutParams(params);
        FilmsUi.focusRing(row, row, FilmsUi.CARD, null);
        row.setOnClickListener(v -> play(stream));

        return row;
    }

    private void playBest() {
        if (!mStreams.isEmpty()) {
            play(mStreams.get(0));
        }
    }

    private void play(Stream stream) {
        String videoId = videoId();
        Entry entry = mProgress.get(videoId);
        Intent intent = new Intent().setClassName(this, UtubotFilmsDeveloperPresenter.FILMS_ACTIVITY)
                .putExtra(UtubotFilmsDeveloperPresenter.EXTRA_IMDB_ID, videoId)
                .putExtra(RealDebridFilmsActivity.EXTRA_TYPE, mItem.isSeries() ? UtubotRealDebridClient.TYPE_SERIES : UtubotRealDebridClient.TYPE_MOVIE)
                .putExtra(RealDebridFilmsActivity.EXTRA_TITLE_ID, mItem.id)
                .putExtra(RealDebridFilmsActivity.EXTRA_NAME, mItem.name)
                .putExtra(RealDebridFilmsActivity.EXTRA_POSTER, mItem.poster)
                .putExtra(RealDebridFilmsActivity.EXTRA_SEASON, mItem.isSeries() && mEpisode != null ? mEpisode.season : 0)
                .putExtra(RealDebridFilmsActivity.EXTRA_EPISODE, mItem.isSeries() && mEpisode != null ? mEpisode.number : 0)
                .putExtra(RealDebridFilmsActivity.EXTRA_STREAM_URL, stream.url)
                .putExtra(RealDebridFilmsActivity.EXTRA_STREAM_NAME, stream.name)
                .putExtra(RealDebridFilmsActivity.EXTRA_START_MS, entry == null ? 0L : entry.resumeMs());
        startActivity(intent);
    }

    @Override
    protected void onDestroy() {
        mDestroyed = true;
        mIo.shutdownNow();
        super.onDestroy();
    }
}
