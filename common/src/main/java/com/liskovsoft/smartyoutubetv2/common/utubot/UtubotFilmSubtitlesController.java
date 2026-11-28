package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.BasePlayerController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.Choice;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmSubtitles.External;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSubtitlePicker.Embedded;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSubtitlePicker.Entry;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * The "Subtitles" button of the player for a film: one picker with the file's own tracks and the subtitles from the internet (listed
 * and fetched by the backend, which already holds the add-on client and its cache), and a delay for the ones from the internet. The
 * choice and its delay are kept per title and applied again when the title is played again.
 */
public class UtubotFilmSubtitlesController extends BasePlayerController {
    private static final String TAG = UtubotFilmSubtitlesController.class.getSimpleName();
    private static final int TIMEOUT_MS = 20_000;
    private static final long[] DELAY_STEPS_MS = {-5_000, -2_000, -1_000, -500, -250, 0, 250, 500, 1_000, 2_000, 5_000};
    private Disposable mAction;

    @Override
    public void onButtonClicked(int buttonId, int buttonState) {
        Video video = getVideo();

        if (buttonId == R.id.action_utubot_films_subtitles && video != null && video.isFilm() && getPlayer() != null) {
            showPicker(video);
        }
    }

    @Override
    public void onNewVideo(Video item) {
        RxHelper.disposeActions(mAction);
    }

    @Override
    public void onEngineReleased() {
        RxHelper.disposeActions(mAction);
    }

    /** The tracks are there: the title's own choice goes back on */
    @Override
    public void onVideoLoaded(Video video) {
        if (video == null || !video.isFilm() || getPlayer() == null) {
            return;
        }

        Choice choice = new UtubotFilmSubtitles.Store(getContext()).get(video.film.progressId);

        if (choice == null) {
            return;
        }

        if (Choice.EXTERNAL.equals(choice.kind)) {
            applyExternal(video, choice, null);
        } else if (Choice.OFF.equals(choice.kind)) {
            getPlayer().setFormat(FormatItem.SUBTITLE_NONE);
        } else {
            FormatItem track = findEmbedded(choice.id);

            if (track != null) {
                getPlayer().setFormat(track);
            }
        }
    }

    @Nullable
    private FormatItem findEmbedded(String id) {
        List<FormatItem> formats = getPlayer().getSubtitleFormats();

        for (FormatItem format : formats == null ? Collections.<FormatItem>emptyList() : formats) {
            if (id.equals(format.getFormatId())) {
                return format;
            }
        }

        return null;
    }

    private void showPicker(Video video) {
        UtubotFilmPlay film = video.film;
        UtubotSettings settings = UtubotSettings.instance(getContext());
        film.setSubtitleLanguage(com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData.instance(getContext()).getSubtitleLanguage());

        if (!settings.isConfigured()) {
            openDialog(video, new ArrayList<>(), false);
            return;
        }

        MessageHelpers.showMessage(getContext(), R.string.utubot_films_subtitles_loading);
        RxHelper.disposeActions(mAction);
        mAction = Observable.fromCallable(() -> UtubotFilmSubtitles.parse(new UtubotClient(settings.getUrl(), settings.getToken()).quiet()
                        .filmSubtitles(film, TIMEOUT_MS)))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(list -> openDialog(video, list, true), error -> {
                    Log.e(TAG, "Subtitle list failed: %s", error.getMessage());
                    openDialog(video, new ArrayList<>(), false);
                });
    }

    private void openDialog(Video video, List<External> external, boolean listed) {
        if (getPlayer() == null || video != getVideo()) {
            return;
        }

        UtubotFilmPlay film = video.film;
        Choice stored = new UtubotFilmSubtitles.Store(getContext()).get(film.progressId);
        List<Embedded> embedded = embeddedTracks();
        Choice current = stored != null ? stored : currentEmbedded();
        List<Entry> entries = UtubotSubtitlePicker.build(embedded, external, film.subtitleLanguage(), current,
                getContext().getString(R.string.utubot_films_subtitles_off), getContext().getString(R.string.utubot_films_subtitles_file) + " ",
                getContext().getString(R.string.utubot_films_subtitles_internet) + " ", getContext().getString(R.string.utubot_films_subtitles_best));
        List<OptionItem> options = new ArrayList<>();

        for (Entry entry : entries) {
            options.add(UiOptionItem.from(entry.label, option -> choose(video, entry, current), entry.selected));
        }

        AppDialogPresenter dialog = getAppDialogPresenter();
        dialog.appendRadioCategory(getContext().getString(R.string.utubot_films_subtitles), options);

        long delay = current != null && Choice.EXTERNAL.equals(current.kind) ? current.delayMs : 0;
        List<OptionItem> delays = new ArrayList<>();

        for (long step : DELAY_STEPS_MS) {
            delays.add(UiOptionItem.from(delayLabel(step), option -> setDelay(video, step), step == delay));
        }

        dialog.appendRadioCategory(getContext().getString(R.string.utubot_films_subtitles_delay), delays);
        dialog.showDialog(getContext().getString(R.string.utubot_films_subtitles));

        if (!listed && UtubotSettings.instance(getContext()).isConfigured()) {
            MessageHelpers.showLongMessage(getContext(), R.string.utubot_films_subtitles_unavailable);
        }
    }

    private List<Embedded> embeddedTracks() {
        List<Embedded> tracks = new ArrayList<>();
        List<FormatItem> formats = getPlayer().getSubtitleFormats();

        for (FormatItem format : formats == null ? Collections.<FormatItem>emptyList() : formats) {
            String id = format.getFormatId();

            if (format.isDefault() || id == null || id.startsWith(UtubotFilmSubtitles.TRACK_PREFIX) || UtubotCaptions.isCaptionTrackId(id)) {
                continue;
            }

            CharSequence title = format.getTitle();
            tracks.add(new Embedded(id, format.getLanguage(), title == null ? "" : title.toString(), format));
        }

        return tracks;
    }

    @Nullable
    private Choice currentEmbedded() {
        FormatItem selected = getPlayer().getSubtitleFormat();

        if (selected == null || selected.isDefault() || selected.getFormatId() == null) {
            return null;
        }

        String id = selected.getFormatId();

        if (id.startsWith(UtubotFilmSubtitles.TRACK_PREFIX)) {
            return new Choice(Choice.EXTERNAL, id.substring(UtubotFilmSubtitles.TRACK_PREFIX.length()), selected.getLanguage(), 0);
        }

        return new Choice(Choice.EMBEDDED, id, selected.getLanguage(), 0);
    }

    private void choose(Video video, Entry entry, @Nullable Choice current) {
        UtubotFilmSubtitles.Store store = new UtubotFilmSubtitles.Store(getContext());
        long delay = current != null && Choice.EXTERNAL.equals(current.kind) ? current.delayMs : 0;

        if (UtubotPlayerLog.isEnabled()) {
            UtubotPlayerLog.event("subtitle.select", entry.kind + " " + entry.lang);
        }

        if (Choice.EXTERNAL.equals(entry.kind)) {
            Choice choice = new Choice(Choice.EXTERNAL, entry.id, entry.lang, delay);
            store.set(video.film.progressId, choice);
            applyExternal(video, choice, entry);
        } else if (Choice.EMBEDDED.equals(entry.kind) && entry.handle instanceof FormatItem) {
            store.set(video.film.progressId, new Choice(Choice.EMBEDDED, entry.id, entry.lang, 0));
            getPlayer().setFilmSubtitle(null, "", "", "");
            getPlayer().setFormat((FormatItem) entry.handle);
        } else {
            store.set(video.film.progressId, new Choice(Choice.OFF, "", "", 0));
            getPlayer().setFormat(FormatItem.SUBTITLE_NONE);
        }
    }

    private void setDelay(Video video, long delayMs) {
        UtubotFilmSubtitles.Store store = new UtubotFilmSubtitles.Store(getContext());
        Choice choice = store.get(video.film.progressId);

        if (choice == null || !Choice.EXTERNAL.equals(choice.kind)) {
            MessageHelpers.showLongMessage(getContext(), R.string.utubot_films_subtitles_delay_internet_only);
            return;
        }

        if (UtubotPlayerLog.isEnabled()) {
            UtubotPlayerLog.event("subtitle.delay", delayMs + " ms");
        }

        Choice moved = choice.withDelay(delayMs);
        store.set(video.film.progressId, moved);
        applyExternal(video, moved, null);
    }

    /**
     * Downloads the subtitle if it is not on the TV yet, shifts it by the delay and gives the player the file
     */
    private void applyExternal(Video video, Choice choice, @Nullable Entry entry) {
        UtubotFilmPlay film = video.film;
        UtubotSettings settings = UtubotSettings.instance(getContext());
        File raw = UtubotFilmSubtitles.file(getContext(), film.videoId(), choice.id, 0);
        File shifted = UtubotFilmSubtitles.file(getContext(), film.videoId(), choice.id, choice.delayMs);
        String label = entry != null ? entry.label : UtubotSubtitlePicker.languageName(choice.lang);

        if (UtubotPlayerLog.isEnabled()) {
            UtubotPlayerLog.event("subtitle.external.load", choice.lang + " delay " + choice.delayMs + " ms");
        }

        RxHelper.disposeActions(mAction);
        mAction = Observable.fromCallable(() -> {
                    if (!shifted.isFile()) {
                        String text = raw.isFile() ? new String(Files.readAllBytes(raw.toPath()), StandardCharsets.UTF_8)
                                : new UtubotClient(settings.getUrl(), settings.getToken()).quiet().filmSubtitleFile(film, choice.id, TIMEOUT_MS);
                        write(raw, text);
                        write(shifted, UtubotFilmSubtitles.shiftVtt(text, choice.delayMs));
                    }

                    return shifted;
                })
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(file -> {
                    if (getPlayer() != null && video == getVideo()) {
                        getPlayer().setFilmSubtitle(file, choice.id, choice.lang, label);
                    }
                }, error -> {
                    Log.e(TAG, "Subtitle download failed: %s", error.getMessage());
                    UtubotPlayerLog.event("subtitle.external.failed");
                    MessageHelpers.showLongMessage(getContext(), R.string.utubot_films_subtitles_unavailable);
                });
    }

    private static void write(File file, String text) throws IOException {
        File dir = file.getParentFile();

        if (dir != null && !dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("Cannot create the subtitle folder");
        }

        Files.write(file.toPath(), text.getBytes(StandardCharsets.UTF_8));
    }

    private String delayLabel(long ms) {
        if (ms == 0) {
            return getContext().getString(R.string.utubot_films_subtitles_no_delay);
        }

        return (ms > 0 ? "+" : "-") + String.format(java.util.Locale.US, "%.2f", Math.abs(ms) / 1000.0) + " s";
    }
}
