package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.VideoMeta;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import io.reactivex.Observable;
import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.ObservableEmitter;
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
    private static final int MAX_CUTS_CACHE = 200;
    @SuppressLint("StaticFieldLeak")
    private static UtubotManager sInstance;
    private final Context mContext;
    private final UtubotSettings mSettings;
    private final VerdictCache mVerdicts = new VerdictCache(VerdictCache.MAX_ENTRIES);
    /**
     * The generation of the kept summaries: a prompt change or another connection clears them, so a request that was already in
     * flight is not stored after it (it would bring back what was just dropped). Guarded by {@code mSummaries}.
     */
    private long mSummaryGeneration;
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
    /**
     * The cut lists of the session with the ETag each was cached under, so the background refresh can
     * re-validate with If-None-Match. Guarded by this field.
     */
    private final Map<String, CutEntry> mCuts = new LinkedHashMap<String, CutEntry>() {
        @Override
        protected boolean removeEldestEntry(Entry<String, CutEntry> eldest) {
            return size() > MAX_CUTS_CACHE;
        }
    };
    /**
     * The videos whose last background cut refresh failed, so the menu shows the cache under a notice.
     * Guarded by {@link #mCutsLastFailed}.
     */
    private final Set<String> mCutsLastFailed = Collections.newSetFromMap(new ConcurrentHashMap<>());
    private final UtubotDiskCache mDisk;
    /**
     * The generation of the connection of the settings: a switch while the disk cache is being opened makes the opening of the old
     * connection drop what it loaded instead of publishing its scope over the new one. Guarded by {@code mConnectionLock}.
     */
    private long mConnectionGeneration;
    private final Object mConnectionLock = new Object();
    /** The scope of the disk cache for the connection of the settings, null until the backend told its data schema */
    private volatile String mDiskScope;
    /**
     * How often an open disk cache asks the backend version again: an update in place keeps the address but not the answers.
     * Package-private so tests can force the check; only read on io threads.
     */
    volatile long mVersionRecheckMs = 60_000;
    private volatile long mVersionCheckedAt;
    private String mSessionPrompt;
    private PromptList mPrompts;
    private UtubotCaptionsFollower mCaptionsFollower;
    private UtubotCutFollower mCutsFollower;

    private UtubotManager(Context context) {
        this(context, UtubotDiskCache.instance(context));
    }

    UtubotManager(Context context, UtubotDiskCache disk) {
        mContext = context.getApplicationContext();
        mSettings = UtubotSettings.instance(mContext);
        mDisk = disk;
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
    void onConnectionChanged() {
        synchronized (mConnectionLock) {
            mConnectionGeneration++;
            mDiskScope = null;
            mVerdicts.clear();
        }

        synchronized (mSummaries) {
            mSummaryGeneration++;
            mSummaries.clear();
        }

        synchronized (mCaptions) {
            mCaptions.clear();
        }

        synchronized (mCuts) {
            mCuts.clear();
            mCutsLastFailed.clear();
        }

        UtubotCaptionsFollower follower;
        UtubotCutFollower cutsFollower;

        synchronized (this) {
            mPrompts = null;
            mSessionPrompt = null;
            follower = mCaptionsFollower;
            cutsFollower = mCutsFollower;
        }

        if (follower != null) {
            follower.stop();
        }

        if (cutsFollower != null) {
            cutsFollower.stop();
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
        List<VideoMeta> unknown = metas;

        // The verdicts of earlier sessions come in with the scope: the videos they know are not asked again
        if (useDiskCache(client)) {
            unknown = new ArrayList<>();

            for (VideoMeta meta : metas) {
                if (mVerdicts.get(meta.videoId) == null) {
                    unknown.add(meta);
                }
            }

            if (unknown.isEmpty()) {
                return true;
            }
        }

        List<Verdict> verdicts = client.assess(unknown, section, waitMs, hardTimeoutMs);

        if (isCurrent(client)) {
            for (Verdict verdict : verdicts) {
                mVerdicts.put(verdict);
            }

            if (mDiskScope != null) {
                mDisk.putVerdicts(verdicts);
            }
        }

        return true;
    }

    /**
     * Opens the disk cache for the connection of the client, once per connection: it asks the backend for its version (a new data schema
     * starts with an empty cache) and puts the stored verdicts into the session's. Blocking: only on an io thread. A backend that does
     * not answer leaves the cache closed for now (the next call tries again) and the request goes on without it.
     *
     * @return the disk cache is open for the connection of the client
     */
    boolean useDiskCache(UtubotClient client) {
        if (mDiskScope != null) {
            if (!isCurrent(client)) {
                return false;
            }

            return versionStillCurrent(client);
        }

        try {
            String scope = UtubotDiskCache.scopeOf(mSettings.getUrl(), mSettings.getToken(), client.cacheSchema());

            if (!isCurrent(client)) {
                return false;
            }

            long generation;
            List<Verdict> stored;
            List<UtubotDiskCache.CutListCache> storedCuts;

            synchronized (mDisk) {
                synchronized (mConnectionLock) {
                    if (!isCurrent(client)) {
                        return false;
                    }

                    generation = mConnectionGeneration;
                }

                mDisk.useScope(scope);
                stored = mDisk.loadVerdicts();
                storedCuts = mDisk.loadCuts();
            }

            synchronized (mConnectionLock) {
                // A switch while the old connection's disk was being opened: what it loaded belongs to the old backend
                if (generation != mConnectionGeneration || !isCurrent(client)) {
                    return false;
                }

                for (Verdict verdict : stored) {
                    if (mVerdicts.get(verdict.videoId) == null) {
                        mVerdicts.put(verdict);
                    }
                }

                for (UtubotDiskCache.CutListCache entry : storedCuts) {
                    if (entry.cuts != null && entry.cuts.configured && entry.videoId != null) {
                        mCuts.put(entry.videoId, new CutEntry(entry.cuts, entry.etag));
                    }
                }

                mDiskScope = scope;
                mVersionCheckedAt = System.currentTimeMillis();
            }

            return true;
        } catch (IOException | RuntimeException error) {
            Log.d(TAG, "The disk cache stays closed: %s", error.getMessage());
            return false;
        }
    }

    /**
     * The backend may have changed the shape of its data in place (a new schema at the same address): its answers are not the old ones. Checked at
     * most once per {@link #mVersionRecheckMs}, so a request does not pay an extra health call every time.
     */
    private boolean versionStillCurrent(UtubotClient client) {
        long now = System.currentTimeMillis();
        long generation;
        String scope;

        synchronized (mConnectionLock) {
            if (mDiskScope == null || !isCurrent(client)) {
                return mDiskScope != null;
            }

            if (now - mVersionCheckedAt < mVersionRecheckMs) {
                return true;
            }

            // Before the network call: the other io threads do not ask as well while this one waits
            mVersionCheckedAt = now;
            generation = mConnectionGeneration;
            scope = mDiskScope;
        }

        String schema;

        try {
            schema = client.cacheSchema();
        } catch (IOException | RuntimeException error) {
            // The request itself will report an unreachable backend; keep what is on disk for when it is back
            Log.d(TAG, "Can't check the backend version: %s", error.getMessage());
            return true;
        }

        synchronized (mConnectionLock) {
            // A switch of backend, token or disk scope while the health call ran: this answer is not that connection's
            if (generation != mConnectionGeneration || !isCurrent(client) || !scope.equals(mDiskScope)) {
                return false;
            }
        }

        if (UtubotDiskCache.scopeOf(mSettings.getUrl(), mSettings.getToken(), schema).equals(scope)) {
            return true;
        }

        Log.d(TAG, "The backend reports cache schema %s: the caches of the old one start over", schema);
        onConnectionChanged();
        useDiskCache(client);

        return mDiskScope != null && isCurrent(client);
    }

    /**
     * The default prompt or the prompt sets changed: no summary of before is the answer to the same request anymore. The generation
     * moves in the same step, so a request that is already in flight does not store its old prompt's answer after the clear.
     */
    private void forgetSummaries() {
        synchronized (mSummaries) {
            mSummaryGeneration++;
            mSummaries.clear();
            // Under the same lock: a request can neither read nor write a stored summary through the clear
            mDisk.clearSummaries();
        }
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
        // What was asked before a prompt change or a switch belongs to the old request: its answer is shown, but not kept again
        long generation;

        synchronized (mSummaries) {
            generation = mSummaryGeneration;
        }

        if (useDiskCache(client)) {
            synchronized (mSummaries) {
                if (generation == mSummaryGeneration) {
                    Summary stored = mDisk.getSummary(videoId, promptKey);

                    if (stored != null) {
                        mSummaries.put(cacheKey, stored);
                        return stored;
                    }
                }
            }
        }

        Summary summary = client.summary(videoId, promptKey, meta, SUMMARY_WAIT_MS);

        // A transcript state comes back at once: the view shows it and decides (it waits, retries, or asks the user)
        for (int poll = 1; summary.isPending() && !summary.isTransient() && poll < MAX_POLLS; poll++) {
            summary = client.summary(videoId, promptKey, meta, SUMMARY_WAIT_MS);
        }

        if (summary.isReady() && !summary.isTransient() && isCurrent(client)) {
            synchronized (mSummaries) {
                // The caches the request started on were cleared while it waited: the text is the answer to the old prompt
                if (generation == mSummaryGeneration) {
                    mSummaries.put(cacheKey, summary);

                    if (mDiskScope != null) {
                        mDisk.putSummary(promptKey, summary);
                    }
                }
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
    public Observable<Boolean> forgetFailuresObserve(String videoId) {
        return cancellable(client -> {
            client.forgetFailures(videoId);
            return true;
        });
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
    private void forgetPrompts() {
        synchronized (this) {
            mPrompts = null;
        }

        // The default prompt may have changed: a stored summary is the answer to the old one
        forgetSummaries();
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
        return prepareCaptionsObserve(videoId, false);
    }

    public Observable<String> prepareCaptionsObserve(String videoId, boolean force) {
        return Observable.fromCallable(() -> newClient().prepareCaptions(videoId, force)).subscribeOn(Schedulers.io());
    }

    //endregion

    //region Director's cuts

    /**
     * The video starts to play: where its cuts stand, and which request to follow while it waits or builds (see
     * {@link UtubotCutFollower})
     */
    public void followCuts(String videoId, UtubotCutFollower.Listener listener) {
        if (!mSettings.isConfigured() || videoId == null) {
            return;
        }

        cutsFollower().follow(videoId, listener);
    }

    public void stopFollowingCuts(UtubotCutFollower.Listener listener) {
        UtubotCutFollower follower;

        synchronized (this) {
            follower = mCutsFollower;
        }

        if (follower != null) {
            follower.stop(listener);
        }
    }

    /**
     * Whether the player of the video that plays follows this request (it will announce and apply its cut)
     */
    public synchronized boolean isFollowingCut(@Nullable String requestId) {
        return mCutsFollower != null && mCutsFollower.isFollowing(requestId);
    }

    /**
     * The user asked for a cut of the video that plays (the menu) and the backend answered with this request
     */
    public void cutRequested(String videoId, @Nullable String requestId, @Nullable String state) {
        if (!mSettings.isConfigured() || videoId == null) {
            return;
        }

        cutsFollower().requested(videoId, requestId, state);
    }

    private synchronized UtubotCutFollower cutsFollower() {
        if (mCutsFollower == null) {
            mCutsFollower = new UtubotCutFollower(UtubotScheduler.mainThread(), new UtubotCutFollower.Fetcher() {
                @Override
                public void fetchCuts(String videoId, UtubotCutFollower.CutsCallback callback) {
                    UtubotClient client = newClient();

                    Observable.<CutList>fromCallable(() -> client.cuts(videoId))
                            .subscribeOn(Schedulers.io()).observeOn(AndroidSchedulers.mainThread())
                            .subscribe(cuts -> {
                                if (isCurrent(client)) {
                                    callback.onResult(cuts);
                                }
                            }, error -> {
                                Log.d(TAG, "No cuts of %s: %s", videoId, error.getMessage());
                                callback.onError(error);
                            });
                }

                @Override
                public void fetchRequest(String requestId, int waitMs, UtubotCutFollower.RequestCallback callback) {
                    UtubotClient client = newClient();

                    Observable.<CutRequest>fromCallable(() -> client.cut(requestId, waitMs))
                            .subscribeOn(Schedulers.io()).observeOn(AndroidSchedulers.mainThread())
                            .subscribe(request -> {
                                if (isCurrent(client)) {
                                    callback.onResult(request);
                                }
                            }, error -> {
                                Log.d(TAG, "No cut request %s: %s", requestId, error.getMessage());
                                callback.onError(error);
                            });
                }
            }, System::currentTimeMillis);
        }

        return mCutsFollower;
    }

    /**
     * The viewer chose this preset for the video (the picker, the player, Apply on the ready prompt): the next open applies it and
     * the preset becomes the one used last for the user. Best-effort: the cut already plays even when the write fails.
     */
    public void rememberCutChoice(String videoId, @Nullable String presetId) {
        if (!mSettings.isConfigured() || mSettings.getToken().isEmpty() || videoId == null || presetId == null) {
            return;
        }

        Observable.fromCallable(() -> {
            newClient().chooseCut(videoId, presetId, null, false);
            return true;
        }).subscribeOn(Schedulers.io()).subscribe(ignored -> { },
                error -> Log.d(TAG, "Can't remember the cut choice of %s: %s", videoId, error.getMessage()));
    }

    /**
     * The viewer turned the cut off for this video: the next open plays uncut instead of taking the preset used last.
     */
    public void forgetCutChoice(String videoId) {
        if (!mSettings.isConfigured() || mSettings.getToken().isEmpty() || videoId == null) {
            return;
        }

        Observable.fromCallable(() -> {
            newClient().chooseCut(videoId, null, null, true);
            return true;
        }).subscribeOn(Schedulers.io()).subscribe(ignored -> { },
                error -> Log.d(TAG, "Can't remember the cut choice of %s: %s", videoId, error.getMessage()));
    }

    /**
     * The cached cut list of a video at once (shown immediately), refreshed in the background with
     * If-None-Match: a fresh list or a 304 does not rebuild an open menu, only a failure shows the cache
     * under a notice. The presets are cheap, so the cache is the menu's first frame when the server is slow.
     * The video facts (the channel id) are forwarded, so the served list resolves the picker's default mode
     * the same way a live fetch does.
     */
    public Observable<CutUpdate> cutsObserve(String videoId, @Nullable VideoMeta meta) {
        return Observable.<CutUpdate>create(emitter -> {
            if (!mSettings.isConfigured() || videoId == null) {
                emitter.onComplete();
                return;
            }

            synchronized (mCuts) {
                CutEntry entry = mCuts.get(videoId);

                if (entry != null && !emitter.isDisposed()) {
                    emitter.onNext(new CutUpdate(entry.cuts, false, true));
                }
            }

            refreshCuts(videoId, meta, emitter);
        }).subscribeOn(Schedulers.io());
    }

    /**
     * Stores a channel's cut mode, or clears it with a null mode so it follows the user default
     */
    public Observable<Boolean> channelCutModeObserve(String channelId, @Nullable String mode, @Nullable String channelName) {
        return cancellable(client -> {
            if (mode == null) {
                client.clearChannelMode(channelId);
            } else {
                client.setChannelMode(channelId, mode, channelName);
            }
            return true;
        });
    }

    /**
     * A cut list to show the menu: the cache shown at once, refreshed in the background, and whether the
     * dialog is to be rebuilt. A fresh list or a 304 do not rebuild an open menu (to keep its place on the
     * TV), only the cache shown at once and a failure that shows it under a notice.
     */
    public static final class CutUpdate {
        public final CutList cuts;
        public final boolean stale;
        public final boolean render;

        public CutUpdate(CutList cuts, boolean stale, boolean render) {
            this.cuts = cuts;
            this.stale = stale;
            this.render = render;
        }
    }

    private void refreshCuts(String videoId, @Nullable VideoMeta meta, ObservableEmitter<CutUpdate> emitter) {
        UtubotClient client = newClient();
        emitter.setCancellable(client::cancel);
        String ifNoneMatch;
        boolean hadCache;
        String cachedEtag;

        synchronized (mCuts) {
            CutEntry entry = mCuts.get(videoId);
            hadCache = entry != null;
            ifNoneMatch = entry != null ? entry.etag : null;
            cachedEtag = ifNoneMatch;
        }

        Observable.<UtubotClient.CutCache>fromCallable(() -> client.cutsCache(videoId, ifNoneMatch, meta))
                .subscribeOn(Schedulers.io())
                .subscribe(cache -> {
                    if (!isCurrent(client) || emitter.isDisposed()) {
                        return;
                    }

                    if (cache.notModified) {
                        // 304: the cache is current, keep it and the open menu's place
                        mCutsLastFailed.remove(videoId);
                        emitter.onComplete();
                        return;
                    }

                    if (cache.cuts != null && cache.cuts.configured) {
                        synchronized (mCuts) {
                            mCuts.put(videoId, new CutEntry(cache.cuts, cache.etag));
                            mCutsLastFailed.remove(videoId);
                        }

                        if (mDiskScope != null) {
                            synchronized (mDisk) {
                                mDisk.putCuts(videoId, cache.etag, cache.body);
                            }
                        }

                        // The first load with no cache shows the fresh list, and so does a list that differs from the cache
                        // shown (a cut got ready, the selection moved); an identical one leaves the open menu alone
                        if ((!hadCache || !Helpers.equals(cachedEtag, cache.etag)) && !emitter.isDisposed()) {
                            emitter.onNext(new CutUpdate(cache.cuts, false, true));
                        }
                    }

                    emitter.onComplete();
                }, error -> {
                    Log.d(TAG, "No cuts of %s: %s", videoId, error.getMessage());

                    synchronized (mCuts) {
                        mCutsLastFailed.add(videoId);
                    }

                    if (emitter.isDisposed()) {
                        return;
                    }

                    CutEntry entry = mCuts.get(videoId);

                    if (entry != null) {
                        emitter.onNext(new CutUpdate(entry.cuts, true, true)); // show the cache under a notice
                    } else {
                        emitter.onError(error);
                    }
                });
    }

    /**
     * The cached cut list of a video, fast and in memory (null when there is none)
     */
    @Nullable
    public CutList getCuts(String videoId) {
        synchronized (mCuts) {
            CutEntry entry = mCuts.get(videoId);
            return entry != null ? entry.cuts : null;
        }
    }

    /**
     * The last background refresh of a video's cut list failed: the menu shows the cache under a notice
     */
    public boolean cutsLastFailed(String videoId) {
        return mCutsLastFailed.contains(videoId);
    }

    /**
     * A cached cut list with the ETag it was stored under, for the next If-None-Match
     */
    private static final class CutEntry {
        final CutList cuts;
        final String etag;

        CutEntry(CutList cuts, String etag) {
            this.cuts = cuts;
            this.etag = etag;
        }
    }

    /**
     * Asks for a cut: a preset, a typed prompt, or a waiting request the phone fills
     */
    public Observable<CutRequest> requestCutObserve(String videoId, @Nullable String presetId, @Nullable String prompt,
                                                    boolean awaitPrompt, @Nullable VideoMeta meta) {
        return requestCutObserve(videoId, presetId, prompt, awaitPrompt, meta, null, false);
    }

    /**
     * The same request with an explicit cut mode (null follows the caller's default)
     */
    public Observable<CutRequest> requestCutObserve(String videoId, @Nullable String presetId, @Nullable String prompt,
                                                    boolean awaitPrompt, @Nullable VideoMeta meta, @Nullable String mode) {
        return requestCutObserve(videoId, presetId, prompt, awaitPrompt, meta, mode, false);
    }

    /**
     * As above; `force` builds from u·tubot's own audio transcript even when the video has captions
     */
    public Observable<CutRequest> requestCutObserve(String videoId, @Nullable String presetId, @Nullable String prompt,
                                                    boolean awaitPrompt, @Nullable VideoMeta meta, boolean force) {
        return requestCutObserve(videoId, presetId, prompt, awaitPrompt, meta, null, force);
    }

    /**
     * The full request: an explicit cut mode and `force`
     */
    public Observable<CutRequest> requestCutObserve(String videoId, @Nullable String presetId, @Nullable String prompt,
                                                    boolean awaitPrompt, @Nullable VideoMeta meta, @Nullable String mode,
                                                    boolean force) {
        return cancellable(client -> client.requestCut(videoId, presetId, prompt, awaitPrompt, meta, mode, force));
    }

    /**
     * Where one cut request stands, once (the picker opened again)
     */
    public Observable<CutRequest> cutObserve(String requestId, int waitMs) {
        return cancellable(client -> client.cut(requestId, waitMs));
    }

    /**
     * The address a phone opens straight to a request's cut sheet
     */
    public String cutRequestUrl(String requestId) {
        return newClient().cutRequestUrl(requestId);
    }

    //endregion

    //region Processed videos

    /**
     * The caller's recently processed videos, for the Processed section. Cancelled with the section.
     */
    public Observable<ProcessedList> processedObserve(int limit) {
        return cancellable(client -> client.processed(limit));
    }

    //endregion
}
