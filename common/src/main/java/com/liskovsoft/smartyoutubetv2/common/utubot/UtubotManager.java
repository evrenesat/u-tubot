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
import io.reactivex.schedulers.Schedulers;

/**
 * The app's side of u-tubot: verdicts for the cards (see HiddenVideoResolver and VideoGroup), and the insight, summary, prompt and
 * caption lookups of the menu, the summary panel and the player. Every network call is blocking inside an Rx io task.
 */
public class UtubotManager {
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

    private UtubotManager(Context context) {
        mContext = context.getApplicationContext();
        mSettings = UtubotSettings.instance(mContext);
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

        return Observable.merge(calls).toList().toObservable().map(results -> true).onErrorReturnItem(true);
    }

    private boolean assess(List<VideoMeta> metas, String section, int waitMs, int hardTimeoutMs) throws IOException {
        List<Verdict> verdicts = newClient().assess(metas, section, waitMs, hardTimeoutMs);

        for (Verdict verdict : verdicts) {
            mVerdicts.put(verdict);
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

    public Observable<Insight> insightObserve(Video video) {
        VideoMeta meta = UtubotMeta.from(video);
        return Observable.fromCallable(() -> pollInsight(video.videoId, meta)).subscribeOn(Schedulers.io());
    }

    private Insight pollInsight(String videoId, @Nullable VideoMeta meta) throws IOException {
        UtubotClient client = newClient();
        Insight insight = client.insight(videoId, meta, INSIGHT_WAIT_MS);

        for (int poll = 1; insight.isPending() && poll < MAX_POLLS; poll++) {
            insight = client.insight(videoId, meta, INSIGHT_WAIT_MS);
        }

        return insight;
    }

    /**
     * Ready summaries are kept for the session
     */
    public Observable<Summary> summaryObserve(Video video, @Nullable String promptKey) {
        VideoMeta meta = UtubotMeta.from(video);
        String cacheKey = summaryKey(video.videoId, promptKey);
        Summary cached = getCachedSummary(video.videoId, promptKey);

        if (cached != null) {
            return Observable.just(cached);
        }

        return Observable.fromCallable(() -> pollSummary(video.videoId, promptKey, meta, cacheKey)).subscribeOn(Schedulers.io());
    }

    private Summary pollSummary(String videoId, @Nullable String promptKey, @Nullable VideoMeta meta, String cacheKey) throws IOException {
        UtubotClient client = newClient();
        Summary summary = client.summary(videoId, promptKey, meta, SUMMARY_WAIT_MS);

        for (int poll = 1; summary.isPending() && poll < MAX_POLLS; poll++) {
            summary = client.summary(videoId, promptKey, meta, SUMMARY_WAIT_MS);
        }

        if (!summary.isPending() && !summary.isFailed()) {
            synchronized (mSummaries) {
                mSummaries.put(cacheKey, summary);
            }
        }

        return summary;
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
    public synchronized String getSessionPrompt() {
        return mSessionPrompt;
    }

    public synchronized void setSessionPrompt(@Nullable String key) {
        mSessionPrompt = key;
    }

    public Observable<PromptList> promptsObserve(boolean forceReload) {
        synchronized (this) {
            if (mPrompts != null && !forceReload) {
                return Observable.just(mPrompts);
            }
        }

        return Observable.fromCallable(() -> {
            PromptList list = newClient().prompts();

            synchronized (this) {
                mPrompts = list;
            }

            return list;
        }).subscribeOn(Schedulers.io());
    }

    public Observable<Boolean> importPromptsObserve(String url) {
        return Observable.fromCallable(() -> {
            newClient().importPrompts(url);
            return true;
        }).subscribeOn(Schedulers.io());
    }

    public Observable<Boolean> refreshPromptsObserve() {
        return Observable.fromCallable(() -> {
            newClient().refreshPrompts();
            return true;
        }).subscribeOn(Schedulers.io());
    }

    public Observable<Boolean> setDefaultPromptObserve(String key) {
        return Observable.fromCallable(() -> {
            newClient().setDefaultPrompt(key);
            return true;
        }).subscribeOn(Schedulers.io());
    }

    //endregion

    //region Captions

    public Observable<Captions> captionsObserve(String videoId) {
        return Observable.fromCallable(() -> newClient().captions(videoId)).subscribeOn(Schedulers.io());
    }

    /**
     * Asks for the HQ captions of a video about to play. Ready ones are kept, so the player finds them when it opens the source.
     */
    public void prefetchCaptions(String videoId) {
        if (!mSettings.isConfigured() || videoId == null || getCachedCaptions(videoId) != null) {
            return;
        }

        captionsObserve(videoId).subscribe(captions -> {
            if (captions.isReady()) {
                synchronized (mCaptions) {
                    mCaptions.put(videoId, captions);
                }
            }
        }, error -> Log.d(TAG, "No HQ captions for %s: %s", videoId, error.getMessage()));
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
