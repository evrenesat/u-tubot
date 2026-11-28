package com.liskovsoft.smartyoutubetv2.tv.utubot.films;

import android.content.ActivityNotFoundException;
import android.speech.RecognizerIntent;
import androidx.annotation.Nullable;
import com.liskovsoft.smartyoutubetv2.common.prefs.SearchData;
import com.liskovsoft.smartyoutubetv2.tv.ui.modern.search.ModernVoiceSearch;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.widget.Toast;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.liskovsoft.smartyoutubetv2.common.R;
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
    private static final String ERROR_TAG = "error";

    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService mIo = Executors.newFixedThreadPool(3);
    private UtubotFilmsCatalog mCatalog;
    private UtubotFilmsProgress mProgress;
    private LinearLayout mRows;
    private LinearLayout mContinueSlot;
    private LinearLayout mResultsSlot;
    private TextView mStatus;
    private EditText mSearch;
    private boolean mInitialFocusDone;
    private boolean mFocusOnRetry;
    private boolean mDestroyed;
    private ModernVoiceSearch mVoice;
    private static final int REQUEST_VOICE = 1;

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
        mRows.setPadding(0, FilmsUi.dp(this, 8), 0, FilmsUi.dp(this, 16));
        scroll.addView(mRows, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(scroll);

        buildHeader();
        setupVoice();
        mContinueSlot = slot();
        mResultsSlot = slot();

        if (settings.getFilmsAddonUrl().isEmpty()) {
            setStatus(getString(R.string.utubot_films_no_addon));
        }

        loadRow(UtubotRealDebridClient.TYPE_MOVIE, UtubotFilmsCatalog.POPULAR, "Popular films", true);
        loadRow(UtubotRealDebridClient.TYPE_MOVIE, UtubotFilmsCatalog.TRENDING, "Trending films", false);
        loadRow(UtubotRealDebridClient.TYPE_SERIES, UtubotFilmsCatalog.POPULAR, "Popular series", false);
    }

    private void buildHeader() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(android.view.Gravity.CENTER_VERTICAL);
        bar.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN), 0, FilmsUi.dp(this, FilmsUi.MARGIN), 0);

        TextView title = FilmsUi.text(this, "Films", 24, FilmsUi.TEXT, true);
        title.setPadding(0, 0, FilmsUi.dp(this, 28), 0);
        bar.addView(title);

        EditText search = new EditText(this);
        search.setHint("Search films and series");
        search.setHintTextColor(FilmsUi.TEXT_DIM);
        search.setTextColor(FilmsUi.TEXT);
        search.setTextSize(FilmsUi.BODY_SP);
        search.setSingleLine();
        search.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        search.setPadding(FilmsUi.dp(this, 16), FilmsUi.dp(this, 6), FilmsUi.dp(this, 16), FilmsUi.dp(this, 6));
        FilmsUi.focusRing(search, search, FilmsUi.CARD, null, null);
        search.setFocusableInTouchMode(true);
        mSearch = search;
        search.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEARCH || event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER) {
                search(search.getText().toString());
                return true;
            }

            return false;
        });
        bar.addView(search, new LinearLayout.LayoutParams(FilmsUi.dp(this, 420), ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView mic = FilmsUi.button(this, "Speak", FilmsUi.BODY_SP, v -> mVoice.start());
        LinearLayout.LayoutParams micParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        micParams.setMargins(FilmsUi.dp(this, 12), 0, 0, 0);
        bar.addView(mic, micParams);
        mRows.addView(bar);

        mStatus = FilmsUi.text(this, "", FilmsUi.BODY_SP, FilmsUi.WARN, false);
        mStatus.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN), FilmsUi.dp(this, 6), FilmsUi.dp(this, FilmsUi.MARGIN), 0);
        mStatus.setVisibility(View.GONE);
        mRows.addView(mStatus);
    }

    /** Voice search is the one of the YouTube search: the same recognizer and the same "Instant voice search" setting (opens the mic at once) */
    private void setupVoice() {
        mVoice = new ModernVoiceSearch(this, new ModernVoiceSearch.Callback() {
            @Override
            public void onListening(boolean listening) {
                mSearch.setHint(listening ? "Listening..." : "Search films and series");
            }

            @Override
            public void onPartialResult(String text) {
                mSearch.setText(text);
            }

            @Override
            public void onResult(String text) {
                mSearch.setText(text);
                search(text);
            }

            @Override
            public void onStartIntent(Intent intent) {
                try {
                    startActivityForResult(intent, REQUEST_VOICE);
                } catch (ActivityNotFoundException e) {
                    Log.w(TAG, "No voice recognizer on this device");
                    mSearch.requestFocus();
                }
            }
        });

        if (SearchData.instance(this).isInstantVoiceSearchEnabled()) {
            mHandler.post(mVoice::start);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, @Nullable Intent data) {
        super.onActivityResult(requestCode, resultCode, data);

        if (requestCode == REQUEST_VOICE && resultCode == RESULT_OK && data != null) {
            List<String> results = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);

            if (results != null && !results.isEmpty()) {
                mSearch.setText(results.get(0));
                search(results.get(0));
            }
        }
    }

    private void setStatus(String text) {
        mStatus.setText(text);
        mStatus.setVisibility(text.isEmpty() ? View.GONE : View.VISIBLE);
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

            if (!mInitialFocusDone && mContinueSlot.getChildCount() > 0) {
                mInitialFocusDone = true;
                focusFirstCard(mContinueSlot.getChildAt(1));
            }
        }
    }

    private void showContinueWatching() {
        mContinueSlot.removeAllViews();
        List<View> cards = new ArrayList<>();

        for (UtubotFilmsProgress.Row row : mProgress.continueRow(System.currentTimeMillis())) {
            cards.add(FilmsUi.posterCard(this, row.name, row.subtitle(), row.poster, row.share(), false,
                    v -> openDetails(row.type, row.titleId, row.name, row.poster),
                    v -> {
                        mProgress.removeFromContinue(row.titleId, System.currentTimeMillis());
                        Toast.makeText(this, row.name + " removed from Continue watching", Toast.LENGTH_SHORT).show();
                        showContinueWatching();
                        return true;
                    }));
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
        mResultsSlot.addView(FilmsUi.rowHeader(this, "Search results for \"" + text + "\""));
        mResultsSlot.addView(row(placeholders()));
        setStatus("");
        mIo.execute(() -> {
            try {
                List<Item> found = new ArrayList<>(mCatalog.search(UtubotRealDebridClient.TYPE_MOVIE, text));
                found.addAll(mCatalog.search(UtubotRealDebridClient.TYPE_SERIES, text));
                mHandler.post(() -> showResults(text, found));
            } catch (Exception e) {
                Log.w(TAG, "Search failed: " + e.getMessage());
                mHandler.post(() -> showSearchError(text));
            }
        });
    }

    private void showSearchError(String text) {
        if (mDestroyed) {
            return;
        }

        mResultsSlot.removeAllViews();
        mResultsSlot.addView(FilmsUi.rowHeader(this, "Search results for \"" + text + "\""));
        mResultsSlot.addView(errorPadded("Search did not work. Check the connection and try again.", () -> search(text)));
    }

    private void showResults(String text, List<Item> found) {
        if (mDestroyed) {
            return;
        }

        mResultsSlot.removeAllViews();

        if (found.isEmpty()) {
            setStatus("Nothing found for \"" + text + "\"");
            return;
        }

        setStatus("");
        mResultsSlot.addView(FilmsUi.rowHeader(this, "Search results for \"" + text + "\""));
        View row = row(cards(found, true));
        mResultsSlot.addView(row);
        focusFirstCard(row);
    }

    private void loadRow(String type, String catalog, String header, boolean takeFocus) {
        LinearLayout slot = slot();
        slot.addView(FilmsUi.rowHeader(this, header));
        fillRow(slot, type, catalog, header, takeFocus);
    }

    private void fillRow(LinearLayout slot, String type, String catalog, String header, boolean takeFocus) {
        while (slot.getChildCount() > 1) {
            slot.removeViewAt(1);
        }

        slot.addView(row(placeholders()));
        mIo.execute(() -> {
            try {
                List<Item> items = mCatalog.list(type, catalog);
                mHandler.post(() -> {
                    if (mDestroyed) {
                        return;
                    }

                    while (slot.getChildCount() > 1) {
                        slot.removeViewAt(1);
                    }

                    if (items.isEmpty()) {
                        slot.removeAllViews();
                        return;
                    }

                    View row = row(cards(items, false));
                    slot.addView(row);

                    if (takeFocus && !mInitialFocusDone && (getCurrentFocus() == null || getCurrentFocus() == mSearch)) {
                        mInitialFocusDone = true;
                        focusFirstCard(row);
                    }
                });
            } catch (Exception e) {
                Log.w(TAG, header + " failed: " + e.getMessage());
                mHandler.post(() -> {
                    if (mDestroyed) {
                        return;
                    }

                    while (slot.getChildCount() > 1) {
                        slot.removeViewAt(1);
                    }

                    View error = errorPadded("Cannot load the " + header.toLowerCase(java.util.Locale.US) + ". Check the connection and try again.",
                            () -> fillRow(slot, type, catalog, header, takeFocus));
                    slot.addView(error);

                    if (mFocusOnRetry || getCurrentFocus() == null || getCurrentFocus() == mSearch) {
                        mFocusOnRetry = true;
                        focusFirstError();
                    }
                });
            }
        });
    }

    /** The Retry button nearest the top, so a failed start puts the focus on the first row that needs it */
    private void focusFirstError() {
        for (int i = 0; i < mRows.getChildCount(); i++) {
            View child = mRows.getChildAt(i);

            if (child instanceof ViewGroup) {
                ViewGroup slot = (ViewGroup) child;

                for (int j = 0; j < slot.getChildCount(); j++) {
                    if (ERROR_TAG.equals(slot.getChildAt(j).getTag())) {
                        FilmsUi.retryButton(((ViewGroup) slot.getChildAt(j)).getChildAt(0)).requestFocus();
                        return;
                    }
                }
            }
        }
    }

    private View errorPadded(String message, Runnable retry) {
        LinearLayout holder = new LinearLayout(this);
        holder.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN), 0, FilmsUi.dp(this, FilmsUi.MARGIN), FilmsUi.dp(this, 8));
        holder.setClipChildren(false);
        holder.setClipToPadding(false);
        holder.setTag(ERROR_TAG);
        holder.addView(FilmsUi.errorBlock(this, message, v -> retry.run()), new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        return holder;
    }

    private List<View> placeholders() {
        List<View> cards = new ArrayList<>();

        for (int i = 0; i < FilmsUi.PLACEHOLDER_CARDS; i++) {
            cards.add(FilmsUi.placeholderCard(this));
        }

        return cards;
    }

    private void focusFirstCard(View row) {
        View first = ((ViewGroup) ((ViewGroup) row).getChildAt(0)).getChildAt(0);
        first.post(first::requestFocus);
    }

    private List<View> cards(List<Item> items, boolean labelKind) {
        List<View> cards = new ArrayList<>();

        for (Item item : items) {
            String subtitle = labelKind ? (item.year.isEmpty() ? "" : item.year + " \u00b7 ") + (item.isSeries() ? "Series" : "Film") : item.year;
            cards.add(FilmsUi.posterCard(this, item.name, subtitle, item.poster, 0f, mProgress.isWatched(item.id),
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
        row.setPadding(FilmsUi.dp(this, FilmsUi.MARGIN - 8), 0, FilmsUi.dp(this, FilmsUi.MARGIN), 0);
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
    protected void onPause() {
        super.onPause();

        if (mVoice != null) {
            mVoice.stop();
        }
    }

    @Override
    protected void onDestroy() {
        mDestroyed = true;
        mIo.shutdownNow();
        super.onDestroy();
    }
}
