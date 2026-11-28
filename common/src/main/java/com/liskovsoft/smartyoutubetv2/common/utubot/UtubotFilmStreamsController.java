package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.BasePlayerController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotRealDebridClient.Stream;

import java.util.ArrayList;
import java.util.List;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;
import io.reactivex.schedulers.Schedulers;

/**
 * The "Streams" button of the player for a film: lists the other streams of the title and plays the one picked from the same position.
 */
public class UtubotFilmStreamsController extends BasePlayerController {
    private static final String TAG = UtubotFilmStreamsController.class.getSimpleName();
    private Disposable mAction;

    @Override
    public void onButtonClicked(int buttonId, int buttonState) {
        Video video = getVideo();

        if (buttonId == R.id.action_utubot_films_streams && video != null && video.isFilm()) {
            loadStreams(video);
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

    private void loadStreams(Video video) {
        UtubotFilmPlay film = video.film;
        UtubotSettings settings = UtubotSettings.instance(getContext());
        UtubotRealDebridClient client = new UtubotRealDebridClient(settings.getFilmsAddonUrl(), settings.getFilmsRealDebridToken());
        UtubotFilmDevice device = new UtubotFilmDevice(getContext());

        MessageHelpers.showMessage(getContext(), R.string.utubot_films_streams_loading);
        RxHelper.disposeActions(mAction);
        mAction = Observable.fromCallable(() -> UtubotRealDebridClient.sortedFor(client.streams(film.type, film.progressId), device))
                .subscribeOn(Schedulers.io())
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(streams -> showStreams(video, streams), error -> {
                    Log.e(TAG, "Streams failed: %s", error.getMessage()); // the message never holds the address
                    MessageHelpers.showLongMessage(getContext(), R.string.utubot_films_failed);
                });
    }

    private void showStreams(Video video, List<Stream> streams) {
        if (getPlayer() == null || video != getVideo() || streams.isEmpty()) {
            MessageHelpers.showLongMessage(getContext(), R.string.utubot_films_no_streams);
            return;
        }

        List<OptionItem> options = new ArrayList<>();

        for (Stream stream : streams) {
            boolean current = stream.url.equals(video.film.streamUrl);
            options.add(UiOptionItem.from(stream.display(), option -> play(video, stream), current));
        }

        AppDialogPresenter dialog = AppDialogPresenter.instance(getContext());
        dialog.appendRadioCategory(getContext().getString(R.string.utubot_films_streams), options);
        dialog.showDialog(getContext().getString(R.string.utubot_films_streams));
    }

    private void play(Video video, Stream stream) {
        if (getPlayer() == null || video != getVideo() || stream.url.equals(video.film.streamUrl)) {
            return;
        }

        long positionMs = getPlayer().getPositionMs();
        video.film = video.film.withStream(stream.url, stream.name, stream.sizeBytes, positionMs);
        video.secondTitle = stream.name;
        AppDialogPresenter.instance(getContext()).closeDialog();
        getMainController().onNewVideo(video);
    }
}
