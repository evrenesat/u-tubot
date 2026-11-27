package com.liskovsoft.smartyoutubetv2.tv.utubot.films;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsCatalog.Item;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmsProgress.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The films home on the TV: a search field and rows of posters (Continue watching, Popular, Trending, Series). A poster opens the details
 * screen. Back leaves to where the films were opened from; it never quits the app.
 */
public class FilmsHomeActivity extends Activity {
    private static final String TAG = "UtubotFilmsHome";

    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService mIo = Executors.newFixedThreadPool(3);
    private UtubotFilmsCatalog mCatalog;
    private UtubotFilmsProgress mProgress;
    private LinearLayout mRows;
    private LinearLayout mContinueSlot;
    private LinearLayout mResultsSlot;
    private TextView mStatus;
    private boolean mDestroyed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        UtubotSettings settings = UtubotSettings.instance(this);

        if (!settings.isFilmsDeveloperEnabled()) {
            finish();
            return;
        }

        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);
        mCatalog = new UtubotFilmsCatalog(settings.getFilmsCatalogUrl());
        mProgress = new UtubotFilmsProgress(this);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(FilmsUi.BACKGROUND);
        scroll.setFillViewport(true);
        scroll.setFocusable(false);
        mRows = new LinearLayout(this);
        mRows.setOrientation(LinearLayout.VERTICAL);
        mRows.setPadding(0, FilmsUi.dp(this, 24), 0, FilmsUi.dp(this, 24));
        scroll.addView(mRows, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(scroll);

        buildHeader();
        mContinueSlot = slot();
        mResultsSlot = slot();

        if (settings.getFilmsAddonUrl().isEmpty()) {
            mStatus.setText("Set the stream addon in Settings, Updates, Films (developer) to play films.");
        }

        loadRow(UtubotRealDebridClient.TYPE_MOVIE, UtubotFilmsCatalog.POPULAR, "Popular films", true);
        loadRow(UtubotRealDebridClient.TYPE_MOVIE, UtubotFilmsCatalog.TRENDING, "Trending films", false);
        loadRow(UtubotRealDebridClient.TYPE_SERIES, UtubotFilmsCatalog.POPULAR, "Popular series", false);
    }

    private void buildHeader() {
        TextView title = FilmsUi.text(this, "Films", 28, FilmsUi.TEXT, true);
        title.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN), 0, FilmsUi.dp(this, FilmsUi.MARGIN), FilmsUi.dp(this, 8));
        mRows.addView(title);

        EditText search = new EditText(this);
        search.setHint("Search films and series");
        search.setHintTextColor(FilmsUi.TEXT_DIM);
        search.setTextColor(FilmsUi.TEXT);
        search.setTextSize(FilmsUi.BODY_SP);
        search.setSingleLine();
        search.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        search.setPadding(FilmsUi.dp(this, 16), FilmsUi.dp(this, 10), FilmsUi.dp(this, 16), FilmsUi.dp(this, 10));
        FilmsUi.focusRing(search, search, FilmsUi.CARD, null);
        search.setFocusableInTouchMode(true);
        search.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEARCH || event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER) {
                search(search.getText().toString());
                return true;
            }

            return false;
        });
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(FilmsUi.dp(this, 480), ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(FilmsUi.dp(this, FilmsUi.MARGIN), 0, 0, 0);
        mRows.addView(search, params);

        mStatus = FilmsUi.text(this, "", FilmsUi.CHIP_SP + 2, FilmsUi.WARN, false);
        mStatus.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN), FilmsUi.dp(this, 8), FilmsUi.dp(this, FilmsUi.MARGIN), 0);
        mRows.addView(mStatus);
    }

    private LinearLayout slot() {
        LinearLayout slot = new LinearLayout(this);
        slot.setOrientation(LinearLayout.VERTICAL);
        mRows.addView(slot);

        return slot;
    }

    @Override
    protected void onResume() {
        super.onResume();

        if (mProgress != null) {
            showContinueWatching();
        }
    }

    private void showContinueWatching() {
        mContinueSlot.removeAllViews();
        List<View> cards = new ArrayList<>();

        for (Entry entry : mProgress.continueWatching()) {
            String subtitle = entry.season > 0 ? "S" + entry.season + " E" + entry.episode : FilmsUi.clock(entry.positionMs);
            cards.add(FilmsUi.posterCard(this, entry.name, subtitle, entry.poster, entry.share(), false,
                    v -> openDetails(entry.type, entry.titleId, entry.name, entry.poster)));
        }

        if (!cards.isEmpty()) {
            mContinueSlot.addView(FilmsUi.rowHeader(this, "Continue watching"));
            mContinueSlot.addView(row(cards));
        }
    }

    private void search(String text) {
        if (text.trim().isEmpty()) {
            return;
        }

        mResultsSlot.removeAllViews();
        mStatus.setText("Searching...");
        mIo.execute(() -> {
            try {
                List<Item> found = new ArrayList<>(mCatalog.search(UtubotRealDebridClient.TYPE_MOVIE, text));
                found.addAll(mCatalog.search(UtubotRealDebridClient.TYPE_SERIES, text));
                mHandler.post(() -> showResults(text, found));
            } catch (Exception e) {
                Log.w(TAG, "Search failed: " + e.getMessage());
                mHandler.post(() -> mStatus.setText("Search failed: " + e.getMessage()));
            }
        });
    }

    private void showResults(String text, List<Item> found) {
        if (mDestroyed) {
            return;
        }

        mResultsSlot.removeAllViews();
        mStatus.setText(found.isEmpty() ? "Nothing found for \"" + text + "\"" : "");

        if (!found.isEmpty()) {
            mResultsSlot.addView(FilmsUi.rowHeader(this, "Search results for \"" + text + "\""));
            mResultsSlot.addView(row(cards(found)));
            View first = ((ViewGroup) ((ViewGroup) mResultsSlot.getChildAt(1)).getChildAt(0)).getChildAt(0);
            first.post(first::requestFocus);
        }
    }

    private void loadRow(String type, String catalog, String header, boolean takeFocus) {
        LinearLayout slot = slot();
        mIo.execute(() -> {
            try {
                List<Item> items = mCatalog.list(type, catalog);
                mHandler.post(() -> {
                    if (!mDestroyed && !items.isEmpty()) {
                        slot.addView(FilmsUi.rowHeader(this, header));
                        View row = row(cards(items));
                        slot.addView(row);

                        if (takeFocus) {
                            View first = ((ViewGroup) ((ViewGroup) row).getChildAt(0)).getChildAt(0);
                            first.post(first::requestFocus);
                        }
                    }
                });
            } catch (Exception e) {
                Log.w(TAG, header + " failed: " + e.getMessage());
                mHandler.post(() -> mStatus.setText("Cannot load the catalogue: " + e.getMessage()));
            }
        });
    }

    private List<View> cards(List<Item> items) {
        List<View> cards = new ArrayList<>();

        for (Item item : items) {
            cards.add(FilmsUi.posterCard(this, item.name, item.year, item.poster, 0f, mProgress.isWatched(item.id),
                    v -> openDetails(item.type, item.id, item.name, item.poster)));
        }

        return cards;
    }

    private View row(List<View> cards) {
        HorizontalScrollView scroll = new HorizontalScrollView(this);
        scroll.setHorizontalScrollBarEnabled(false);
        scroll.setClipToPadding(false);
        scroll.setClipChildren(false);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN - 6), 0, FilmsUi.dp(this, FilmsUi.MARGIN), 0);
        row.setClipChildren(false);

        for (View card : cards) {
            row.addView(card);
        }

        scroll.addView(row);

        return scroll;
    }

    private void openDetails(String type, String id, String name, String poster) {
        startActivity(new Intent(this, FilmDetailsActivity.class)
                .putExtra(FilmDetailsActivity.EXTRA_TYPE, type)
                .putExtra(FilmDetailsActivity.EXTRA_ID, id)
                .putExtra(FilmDetailsActivity.EXTRA_NAME, name)
                .putExtra(FilmDetailsActivity.EXTRA_POSTER, poster));
    }

    @Override
    protected void onDestroy() {
        mDestroyed = true;
        mIo.shutdownNow();
        super.onDestroy();
    }
}
