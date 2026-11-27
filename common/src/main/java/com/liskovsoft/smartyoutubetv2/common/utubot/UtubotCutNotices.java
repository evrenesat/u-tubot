package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;

import java.util.ArrayList;
import java.util.List;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.schedulers.Schedulers;

/**
 * The app-wide side of a cut that becomes ready while the viewer is somewhere else (issue 96): it keeps the cuts this TV ordered,
 * follows them through the cut-request status endpoint, and asks "Director's cut ready: ... Play?" wherever the app is. Yes opens the
 * video through the #64 cut path; No, or Back, only closes the question. A failure is a short message; a cut found ready at startup
 * (the app was closed when it finished) is not announced.
 */
public final class UtubotCutNotices {
    private static final String TAG = UtubotCutNotices.class.getSimpleName();
    private static final int PROMPT_DIALOG_ID = 156;
    private static final long DIALOG_RETRY_MS = 1_000;
    @SuppressLint("StaticFieldLeak")
    private static UtubotCutNotices sInstance;
    private final Context mContext;
    private final UtubotSettings mSettings;
    private final UtubotCutWaitlist mWaitlist;
    private final UtubotCutPromptQueue mPrompts;
    private final List<String> mFailures = new ArrayList<>();
    private UtubotCutWatcher mWatcher;
    private boolean mInstalled;
    private boolean mPromptShown;
    private boolean mRetryPosted;

    private UtubotCutNotices(Context context) {
        mContext = context.getApplicationContext();
        mSettings = UtubotSettings.instance(mContext);
        mWaitlist = UtubotCutWaitlist.prefs(mContext);
        mPrompts = new UtubotCutPromptQueue(this::presentPrompt, this::openWithCut);
    }

    public static synchronized UtubotCutNotices instance(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotCutNotices(context);
        }

        return sInstance;
    }

    /**
     * Installed once with the app: the requests kept on the device are checked again, and the list follows a backend or token change.
     */
    public synchronized void install() {
        if (mInstalled) {
            return;
        }

        mInstalled = true;
        mSettings.addConnectionListener(this::onConnectionChanged);
        watcher().start();
    }

    /**
     * A cut this TV just asked for while it was still waiting or building.
     */
    public void ordered(String requestId, String videoId, @Nullable String title) {
        if (requestId == null || videoId == null) {
            return;
        }

        Entry entry = new Entry(requestId, videoId, title, System.currentTimeMillis());
        mWaitlist.add(entry);

        if (mInstalled) {
            watcher().watch(entry);
        }
    }

    /**
     * A screen that is not a dialog came up: show what was kept while the app had no screen, and try a question that was blocked.
     */
    public void onScreenAvailable() {
        flushFailures();
        mPrompts.retry();
    }

    public synchronized void onConnectionChanged() {
        if (mWatcher != null) {
            mWatcher.stop();
        }

        mWaitlist.clear();
        mPrompts.clear();
        mFailures.clear();

        if (mPromptShown) {
            Context screen = UtubotScreen.screenContext();

            if (screen != null) {
                AppDialogPresenter.instance(screen).closeDialog();
            }
        }

        mPromptShown = false;

        if (mInstalled) {
            watcher().start();
        }
    }

    void onCutReady(Entry entry, Cut cut) {
        if (!UtubotScreen.isForeground()) {
            // The app was closed or in the background when the cut became ready: it stays in the picker and the Processed section
            return;
        }

        if (playerTookOverReadyCut(entry, cut)) {
            // The player's own follower announces and applies (or offers) a cut of the video that plays (#64). It follows the request
            // the moment the video opens and clears it when the cut is ready, so "follows" alone would miss a cut the player already
            // took over; a request the player follows has no preset id, so only this check can tell it apart from one ordered elsewhere.
            return;
        }

        // A cut ordered from the thumbnail screen while its picker is still open refreshes that picker (issue 197): the building row
        // stops saying "Building…" and shows the ready state. It is not started here, so the open menu is not taken over.
        if (UtubotMenu.isCutsMenuOpen(entry.videoId)) {
            UtubotMenu.refresh(screenContext(), entry.videoId);
            return;
        }

        // Still browsing the thumbnails with no video playing: the owner is waiting for it, so it opens by itself. A playing video is
        // never interrupted (the player handles its own cut, or this is asked instead); focus moved to other content falls through.
        if (viewerStillWaiting()) {
            openWithCut(new UtubotCutPromptQueue.Item(entry, cut));
            return;
        }

        mPrompts.add(new UtubotCutPromptQueue.Item(entry, cut));
    }

    /**
     * The owner ordered the cut from the thumbnail screen and is still there: no video is playing (nothing to interrupt) and a card of
     * the browse screen has the focus (the cut's video, or another one they are scrolling past). Focus moved off the screen cleared it.
     */
    private boolean viewerStillWaiting() {
        UtubotCutController controller = cutController(screenContext());

        if (controller != null && controller.hasLivePlayer()) {
            return false;
        }

        return UtubotCutFocus.currentVideoId() != null;
    }

    /**
     * The player is handling this ready cut of the video that plays, so the app-wide notice must not also ask: the player's follower
     * still owns the request (across an engine release, before it answers), or it has already applied, queued, or offered the cut.
     */
    private boolean playerTookOverReadyCut(Entry entry, Cut cut) {
        if (followsRequest(entry.requestId)) {
            return true;
        }

        UtubotCutController controller = cutController(screenContext());
        return controller != null && controller.isHandlingReadyCut(cut);
    }

    void onCutFailed(Entry entry, @Nullable String error) {
        String text = error != null && !error.trim().isEmpty()
                ? mContext.getString(R.string.utubot_cut_failed, error)
                : mContext.getString(R.string.utubot_cut_failed_plain);

        if (UtubotScreen.isForeground()) {
            MessageHelpers.showMessage(mContext, text);
        } else {
            mFailures.add(text);
        }
    }

    boolean presentPrompt(UtubotCutPromptQueue.Item item, UtubotCutPromptQueue.Answer answer) {
        Context screen = UtubotScreen.screenContext();

        if (screen == null || !UtubotScreen.isForeground()) {
            return false; // nothing is up: onScreenAvailable tries again
        }

        if (playerTookOverReadyCut(item.entry, item.cut)) {
            // The player took over this cut (applied, queued, or offering) since it was kept: drop the question instead of reopening
            // the same video and discarding the cut the player already has. Resolved as "stay", then the next ready cut is tried.
            answer.stay();
            return true;
        }

        String text = promptText(screen, item.entry, item.cut);
        UtubotCutController controller = cutController(screen);

        if (controller != null && controller.hasLivePlayer()) {
            // A video plays: the question is a notice that does not take the focus or cover the picture. The cut stays in the
            // Director's cut picker and the Processed section, where the owner plays it (issue 274).
            MessageHelpers.showMessage(screen, promptLaterText(screen, item.entry, item.cut));
            answer.stay();
            return true;
        }

        AppDialogPresenter dialog = AppDialogPresenter.instance(screen);

        if (mPromptShown || dialog.isDialogShown()) {
            schedulePromptRetry();
            return false;
        }

        final boolean[] answered = {false};
        OptionItem yes = UiOptionItem.from(screen.getString(R.string.utubot_cut_play_yes), option -> {
            answered[0] = true;
            dialog.closeDialog();
            answer.play();
        });
        OptionItem no = UiOptionItem.from(screen.getString(R.string.utubot_cut_play_no), option -> {
            answered[0] = true;
            dialog.closeDialog();
            answer.stay();
        });

        dialog.appendSingleButton(yes);
        dialog.appendSingleButton(no);
        dialog.setId(PROMPT_DIALOG_ID);
        dialog.setOnFinish(() -> {
            mPromptShown = false;

            if (!answered[0]) {
                answered[0] = true;
                answer.stay();
            }
        });
        // Transparent dialogs over a video hide the title, so the question is the body text of the dialog, not the title (issue 274)
        dialog.appendLongTextCategory(screen.getString(R.string.utubot_cut), UiOptionItem.from(text));
        dialog.enableTransparent(true);
        dialog.enableExpandable(false);

        mPromptShown = true;
        dialog.showDialog();

        return true;
    }

    static String promptText(Context screen, Entry entry, Cut cut) {
        String title = promptTitle(screen, entry);
        String length = UtubotCutController.formatLength(cut.keptMs);

        return length.isEmpty()
                ? screen.getString(R.string.utubot_cut_ready_play_no_length, title)
                : screen.getString(R.string.utubot_cut_ready_play, title, length);
    }

    /** The same question for a video that plays: where to play the cut instead of asking it. */
    static String promptLaterText(Context screen, Entry entry, Cut cut) {
        String title = promptTitle(screen, entry);
        String length = UtubotCutController.formatLength(cut.keptMs);

        return length.isEmpty()
                ? screen.getString(R.string.utubot_cut_ready_later_no_length, title)
                : screen.getString(R.string.utubot_cut_ready_later, title, length);
    }

    private static String promptTitle(Context screen, Entry entry) {
        return entry.title != null && !entry.title.trim().isEmpty()
                ? entry.title.trim() : screen.getString(R.string.utubot_cut);
    }

    private void openWithCut(UtubotCutPromptQueue.Item item) {
        Context screen = UtubotScreen.screenContext();
        Context context = screen != null ? screen : mContext;
        UtubotCutController controller = cutController(context);

        if (controller != null) {
            controller.applyOnOpen(item.cut);
        }

        Video video = Video.from(item.entry.videoId);
        video.title = item.entry.title;

        PlaybackPresenter.instance(context).openVideo(video);
    }

    private boolean followsRequest(@Nullable String requestId) {
        return UtubotManager.instance(mContext).isFollowingCut(requestId);
    }

    private Context screenContext() {
        Context screen = UtubotScreen.screenContext();

        return screen != null ? screen : mContext;
    }

    private UtubotCutController cutController(Context context) {
        return PlaybackPresenter.instance(context).getController(UtubotCutController.class);
    }

    private void schedulePromptRetry() {
        if (mRetryPosted) {
            return;
        }

        mRetryPosted = true;
        UtubotScheduler.mainThread().postDelayed(() -> {
            mRetryPosted = false;
            mPrompts.retry();
        }, DIALOG_RETRY_MS);
    }

    private void flushFailures() {
        if (mFailures.isEmpty()) {
            return;
        }

        for (String text : mFailures) {
            MessageHelpers.showMessage(mContext, text);
        }

        mFailures.clear();
    }

    private synchronized UtubotCutWatcher watcher() {
        if (mWatcher == null) {
            mWatcher = new UtubotCutWatcher(UtubotScheduler.mainThread(), this::fetchRequest, System::currentTimeMillis,
                    mWaitlist, new UtubotCutWatcher.Listener() {
                @Override
                public void onCutReady(Entry entry, Cut cut) {
                    UtubotCutNotices.this.onCutReady(entry, cut);
                }

                @Override
                public void onCutFailed(Entry entry, String error) {
                    UtubotCutNotices.this.onCutFailed(entry, error);
                }
            });
        }

        return mWatcher;
    }

    private void fetchRequest(String requestId, int waitMs, UtubotCutWatcher.Callback callback) {
        UtubotClient client = UtubotManager.instance(mContext).newClient();

        Observable.<CutRequest>fromCallable(() -> client.cut(requestId, waitMs))
                .subscribeOn(Schedulers.io()).observeOn(AndroidSchedulers.mainThread())
                .subscribe(callback::onResult, error -> {
                    Log.d(TAG, "No cut request %s: %s", requestId, error.getMessage());
                    callback.onError(error);
                });
    }
}
