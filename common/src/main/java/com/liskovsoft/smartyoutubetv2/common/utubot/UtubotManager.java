package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.schedulers.Schedulers;

/**
 * The app's side of u-tubot: verdicts for the cards (see HiddenVideoResolver and VideoGroup), and the insight, summary, prompt and
 * caption lookups of the menu, the summary panel and the player. Every network call is blocking inside an Rx io task.
 */
public class UtubotManager implements UtubotPanelModel.Source, UtubotAnswerModel.Source {
    private static final String TAG = UtubotManager.class.getSimpleName();
    public static final int MAX_ASSESS_VIDEOS = 50;
    public static final int INSIGHT_WAIT_MS = 20_000;
    public static final int SUMMARY_WAIT_MS = 20_000;
    public static final int MAX_POLLS = 6;
    private static final int MAX_SUMMARY_CACHE = 100;
    private static final int MAX_CAPTIONS_CACHE = 30;
    @SuppressLint("StaticFieldLeak")
    private static UtubotManager sInstance;
    private final Context mContext;
    private final UtubotSettings mSettings;
    private final VerdictCache mVerdicts = new VerdictCache(VerdictCache.MAX_ENTRIES);
    private final Map<String, Summary> mSummaries = new LinkedHashMap<String, Summary>() {
        @Override
        protected boolean removeEldestEntry(Entry<String, Summary> eldest) {
            return size() > MAX_SUMMARY_CACHE;
        }
    };
    private final Map<String, Captions> mCaptions = new LinkedHashMap<String, Captions>() {
        @Override
        protected boolean removeEldestEntry(Entry<String, Captions> eldest) {
            return size() > MAX_CAPTIONS_CACHE;
        }
    };
    private String mSessionPrompt;
    private PromptList mPrompts;
    private UtubotCaptionsFollower mCaptionsFollower;

    private UtubotManager(Context context) {
        mContext = context.getApplicationContext();
        mSettings = UtubotSettings.instance(mContext);
        mSettings.addConnectionListener(this::onConnectionChanged);
    }

    public static synchronized UtubotManager instance(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotManager(context);
        }

        return sInstance;
    }

    public UtubotSettings getSettings() {
        return mSettings;
    }

    public UtubotClient newClient() {
        return new UtubotClient(mSettings.getUrl(), mSettings.getToken());
    }

    /**
     * Another backend or another token: the verdicts, summaries, captions and prompts of the old connection are not the new one's
     */
    private void onConnectionChanged() {
        mVerdicts.clear();

        synchronized (mSummaries) {
            mSummaries.clear();
        }

        synchronized (mCaptions) {
            mCaptions.clear();
        }

        UtubotCaptionsFollower follower;

        synchronized (this) {
            mPrompts = null;
            mSessionPrompt = null;
            follower = mCaptionsFollower;
        }

        if (follower != null) {
            follower.stop();
        }
    }

    /**
     * The client still talks to the backend of the settings: an answer that arrives after a switch of backend or token is not kept
     */
    private boolean isCurrent(UtubotClient client) {
        return client.isSameConnectionAs(newClient());
    }

    //region Assess

    /**
     * Holds the emission until the verdicts of its videos are in, at most the wait time of the settings plus the network slack.
     * Never fails: with any error the videos are shown as they are.
     */
    public Observable<Boolean> resolve(List<MediaGroup> mediaGroups, @Nullable BrowseSection section) {
        if (!mSettings.isAssessEnabled() || mediaGroups == null) {
            return Observable.just(true);
        }

        Map<String, List<VideoMeta>> metaBySection = collect(mediaGroups, section);

        if (metaBySection.isEmpty()) {
            return Observable.just(true);
        }

        int waitMs = mSettings.getWaitMs();
        int hardTimeoutMs = waitMs + UtubotSettings.NETWORK_SLACK_MS;
        List<Observable<Boolean>> calls = new ArrayList<>();

        for (Map.Entry<String, List<VideoMeta>> entry : metaBySection.entrySet()) {
            List<VideoMeta> metas = entry.getValue();

            for (int from = 0; from < metas.size(); from += MAX_ASSESS_VIDEOS) {
                List<VideoMeta> chunk = metas.subList(from, Math.min(from + MAX_ASSESS_VIDEOS, metas.size()));
                calls.add(Observable.fromCallable(() -> assess(chunk, entry.getKey(), waitMs, hardTimeoutMs))
                        .subscribeOn(Schedulers.io())
                        .onErrorReturn(error -> {
                            Log.e(TAG, "Can't assess the videos: %s", error.getMessage());
                            return false;
                        }));
            }
        }

        // The rows are built and shown from whatever this emits (see BrowsePresenter): the main thread, as the other managers of the
        // resolver do. On the io thread of the last call the adapters of the grids were changed off the UI thread, which raced with the
        // layout (IllegalStateException: Cannot call this method while RecyclerView is computing a layout) and left the section empty.
        return Observable.merge(calls).toList().toObservable().map(results -> true).onErrorReturnItem(true)
                .observeOn(AndroidSchedulers.mainThread());
    }

    private boolean assess(List<VideoMeta> metas, String section, int waitMs, int hardTimeoutMs) throws IOException {
        UtubotClient client = newClient();
        List<Verdict> verdicts = client.assess(metas, section, waitMs, hardTimeoutMs);

        if (isCurrent(client)) {
            for (Verdict verdict : verdicts) {
                mVerdicts.put(verdict);
            }
        }

        return true;
    }

    /**
     * The videos of the groups no verdict is known for, by the section name of their group
     */
    Map<String, List<VideoMeta>> collect(List<MediaGroup> mediaGroups, @Nullable BrowseSection section) {
        Map<String, List<VideoMeta>> result = new HashMap<>();

        for (MediaGroup mediaGroup : mediaGroups) {
            if (mediaGroup == null || mediaGroup.getMediaItems() == null) {
                continue;
            }

            String sectionName = UtubotPolicy.sectionName(VideoGroup.getAiSListSection(mediaGroup.getType(), section, mediaGroup.getChannelId()));

            if (sectionName == null) {
                continue;
            }

            for (MediaItem item : mediaGroup.getMediaItems()) {
                VideoMeta meta = UtubotMeta.from(Video.from(item));

                if (meta != null && mVerdicts.get(meta.videoId) == null) {
                    List<VideoMeta> metas = result.get(sectionName);

                    if (metas == null) {
                        metas = new ArrayList<>();
                        result.put(sectionName, metas);
                    }

                    metas.add(meta);
                }
            }
        }

        return result;
    }

    @Nullable
    public Verdict getVerdict(String videoId) {
        return mVerdicts.get(videoId);
    }

    public void putVerdict(Verdict verdict) {
        mVerdicts.put(verdict);
    }

    /**
     * Applies the cached verdict to the card.
     *
     * @return the card is to be hidden
     */
    public boolean apply(Video video, int aiSListSection) {
        if (!mSettings.isAssessEnabled() || UtubotPolicy.sectionName(aiSListSection) == null) {
            return false;
        }

        Verdict verdict = mVerdicts.get(video.videoId);
        UtubotPolicy.Decision decision = UtubotPolicy.decide(verdict, mSettings.isMarkOnly());

        if (decision == UtubotPolicy.Decision.MARK) {
            video.utubotMark = UtubotPolicy.markLabel(verdict);
        }

        return decision == UtubotPolicy.Decision.HIDE;
    }

    //endregion

    //region Insight, summary, prompts

    /**
     * Runs a blocking call of a client on an io thread. Disposing the observable cancels the call in flight.
     */
    private <T> Observable<T> cancellable(ClientCall<T> call) {
        return Observable.<T>create(emitter -> {
            UtubotClient client = newClient();
            emitter.setCancellable(client::cancel);

            try {
                T result = call.call(client);

                if (!emitter.isDisposed()) {
                    emitter.onNext(result);
                    emitter.onComplete();
                }
            } catch (Throwable error) {
                if (!emitter.isDisposed()) {
                    emitter.onError(error);
                }
            }
        }).subscribeOn(Schedulers.io());
    }

    private interface ClientCall<T> {
        T call(UtubotClient client) throws IOException;
    }

    @Override
    public Observable<Insight> insightObserve(Video video) {
        VideoMeta meta = UtubotMeta.from(video);
        return cancellable(client -> pollInsight(client, video.videoId, meta));
    }

    private Insight pollInsight(UtubotClient client, String videoId, @Nullable VideoMeta meta) throws IOException {
        Insight insight = client.insight(videoId, meta, INSIGHT_WAIT_MS);

        // A transcript state comes back at once, like a summary's
        for (int poll = 1; insight.isPending() && !insight.isTransient() && poll < MAX_POLLS; poll++) {
            insight = client.insight(videoId, meta, INSIGHT_WAIT_MS);
        }

        return insight;
    }

    /**
     * Ready summaries are kept for the session. Nothing else is: a transcript state (no captions, delayed, transcribing), a
     * pending job or a failure is the answer of the moment, and the next request asks again.
     */
    @Override
    public Observable<Summary> summaryObserve(Video video, @Nullable String promptKey) {
        VideoMeta meta = UtubotMeta.from(video);
        String cacheKey = summaryKey(video.videoId, promptKey);
        Summary cached = getCachedSummary(video.videoId, promptKey);

        if (cached != null) {
            return Observable.just(cached);
        }

        return cancellable(client -> pollSummary(client, video.videoId, promptKey, meta, cacheKey));
    }

    private Summary pollSummary(UtubotClient client, String videoId, @Nullable String promptKey, @Nullable VideoMeta meta, String cacheKey)
            throws IOException {
        Summary summary = client.summary(videoId, promptKey, meta, SUMMARY_WAIT_MS);

        // A transcript state comes back at once: the view shows it and decides (it waits, retries, or asks the user)
        for (int poll = 1; summary.isPending() && !summary.isTransient() && poll < MAX_POLLS; poll++) {
            summary = client.summary(videoId, promptKey, meta, SUMMARY_WAIT_MS);
        }

        if (summary.isReady() && !summary.isTransient() && isCurrent(client)) {
            synchronized (mSummaries) {
                mSummaries.put(cacheKey, summary);
            }
        }

        return summary;
    }

    /**
     * Starts the background transcription of a video without captions
     */
    @Override
    public Observable<Transcript> transcribeObserve(Video video) {
        VideoMeta meta = UtubotMeta.from(video);
        return cancellable(client -> client.transcribe(video.videoId, meta));
    }

    @Override
    public Observable<Transcript> transcriptObserve(String videoId) {
        return cancellable(client -> client.transcript(videoId));
    }

    @Nullable
    public Summary getCachedSummary(String videoId, @Nullable String promptKey) {
        synchronized (mSummaries) {
            return mSummaries.get(summaryKey(videoId, promptKey));
        }
    }

    private static String summaryKey(String videoId, @Nullable String promptKey) {
        return videoId + "|" + (promptKey != null ? promptKey : "");
    }

    /**
     * The prompt picked in the panel, for the rest of the session. Null: the backend's default.
     */
    @Nullable
    @Override
    public synchronized String getSessionPrompt() {
        return mSessionPrompt;
    }

    @Override
    public synchronized void setSessionPrompt(@Nullable String key) {
        mSessionPrompt = key;
    }

    @Override
    public Observable<PromptList> promptsObserve(boolean forceReload) {
        synchronized (this) {
            if (mPrompts != null && !forceReload) {
                return Observable.just(mPrompts);
            }
        }

        return cancellable(client -> {
            PromptList list = client.prompts();

            synchronized (this) {
                if (isCurrent(client)) {
                    mPrompts = list;
                }
            }

            return list;
        });
    }

    public Observable<Boolean> importPromptsObserve(String url) {
        return Observable.fromCallable(() -> {
            try {
                newClient().importPrompts(url);
            } finally {
                forgetPrompts();
            }

            return true;
        }).subscribeOn(Schedulers.io());
    }

    public Observable<Boolean> refreshPromptsObserve() {
        return Observable.fromCallable(() -> {
            try {
                newClient().refreshPrompts();
            } finally {
                forgetPrompts();
            }

            return true;
        }).subscribeOn(Schedulers.io());
    }

    public Observable<Boolean> setDefaultPromptObserve(String key) {
        return Observable.fromCallable(() -> {
            try {
                newClient().setDefaultPrompt(key);
            } finally {
                forgetPrompts();
            }

            return true;
        }).subscribeOn(Schedulers.io());
    }

    /**
     * The list on the backend changed (or may have): the next request reads it again
     */
    private synchronized void forgetPrompts() {
        mPrompts = null;
    }

    //endregion

    //region Captions

    public Observable<Captions> captionsObserve(String videoId) {
        return Observable.fromCallable(() -> newClient().captions(videoId)).subscribeOn(Schedulers.io());
    }

    /**
     * The video starts to play: asks for its HQ captions and, while a job is queued or running, keeps asking until they are ready (see
     * {@link UtubotCaptionsFollower}). Ready captions are kept, so the player finds them when it opens the source; the listener hears of
     * the ones that come once the source is open. A video whose captions are kept needs no listener.
     */
    public void followCaptions(String videoId, UtubotCaptionsFollower.Listener listener) {
        // Captions stored on the TV are all there is to ask for
        if (!mSettings.isConfigured() || videoId == null || getCachedCaptions(videoId) != null || UtubotCaptionStore.instance(mContext).has(videoId)) {
            return;
        }

        captionsFollower().follow(videoId, listener);
    }

    public void stopFollowingCaptions(UtubotCaptionsFollower.Listener listener) {
        UtubotCaptionsFollower follower;

        synchronized (this) {
            follower = mCaptionsFollower;
        }

        if (follower != null) {
            follower.stop(listener);
        }
    }

    /**
     * The user asked for the HQ captions of a video (Prepare HQ captions) and the backend answered with this status
     */
    public void captionsRequested(String videoId, @Nullable String status) {
        if (!mSettings.isConfigured() || videoId == null) {
            return;
        }

        captionsFollower().requested(videoId, status);
    }

    private synchronized UtubotCaptionsFollower captionsFollower() {
        if (mCaptionsFollower == null) {
            mCaptionsFollower = new UtubotCaptionsFollower(UtubotScheduler.mainThread(), this::fetchCaptions, System::currentTimeMillis);
        }

        return mCaptionsFollower;
    }

    /**
     * Ready captions are downloaded into the storage of the TV and kept as soon as they are known, off the main thread; the follower
     * hears of them on the main thread
     */
    private void fetchCaptions(String videoId, UtubotCaptionsFollower.Callback callback) {
        UtubotClient client = newClient();

        Observable.fromCallable(() -> {
            Captions captions = client.captions(videoId);

            if (captions.isReady()) {
                storeCaptions(client, videoId, captions);

                if (isCurrent(client)) {
                    synchronized (mCaptions) {
                        mCaptions.put(videoId, captions);
                    }
                }
            }

            return captions;
        }).subscribeOn(Schedulers.io()).observeOn(AndroidSchedulers.mainThread()).subscribe(captions -> {
            if (isCurrent(client)) {
                callback.onResult(captions);
            }
        }, error -> {
            Log.d(TAG, "No HQ captions for %s: %s", videoId, error.getMessage());
            callback.onError(error);
        });
    }

    /**
     * Keeps the files of the tracks that are not stored yet. A track that can't be downloaded now is played from the backend and
     * tried again the next time.
     */
    private void storeCaptions(UtubotClient client, String videoId, Captions captions) {
        UtubotCaptionStore store = UtubotCaptionStore.instance(mContext);

        for (UtubotModels.CaptionTrack track : captions.tracks) {
            if (store.hasTrack(videoId, track.lang)) {
                continue;
            }

            try {
                store.save(videoId, track, client.captionFile(track.url));
            } catch (IOException e) {
                Log.d(TAG, "Can't download the %s captions of %s: %s", track.lang, videoId, e.getMessage());
            }
        }
    }

    @Nullable
    public Captions getCachedCaptions(String videoId) {
        synchronized (mCaptions) {
            return mCaptions.get(videoId);
        }
    }

    public Observable<String> prepareCaptionsObserve(String videoId) {
        return Observable.fromCallable(() -> newClient().prepareCaptions(videoId)).subscribeOn(Schedulers.io());
    }

    //endregion
}
