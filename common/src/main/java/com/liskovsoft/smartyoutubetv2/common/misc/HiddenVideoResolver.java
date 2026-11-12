package com.liskovsoft.smartyoutubetv2.common.misc;

import android.content.Context;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import io.reactivex.Observable;

/**
 * Holds each emission until what hides its videos after a lookup is known: the channel handles of AiSList,
 * the collaborations and Watch later, in the sections they apply to. The groups are then built without those videos (see VideoGroup),
 * so a hidden video never appears first and vanishes after. The categories of Home are held the same way (see VideoCategoryManager).<br/>
 * The dates of shorts are held too (see ShortsDateManager): the card never gets its date after it's shown, and Hide old videos reads it.
 * So are the live streams that ended in History (see StreamedManager): its cards come without the date that tells them.<br/>
 * The u-tubot verdicts are held the same way (see UtubotManager). A failed lookup doesn't hold the group back: its videos are shown.
 */
public class HiddenVideoResolver {
    private static final String TAG = HiddenVideoResolver.class.getSimpleName();
    // The lookups of an emission start while the one before is still held, they come out in their order.
    // More at once would crowd the requests of the rows being filled (see GroupFiller).
    static final int MAX_RESOLVING_EMISSIONS = 2;

    /**
     * @param section the sidebar section of the groups built from the emission or null (e.g. search, a channel)
     */
    public static Observable<List<MediaGroup>> resolveGroups(Context context, Observable<List<MediaGroup>> groups, BrowseSection section) {
        if (groups == null) {
            return null;
        }

        return groups.concatMapEager(mediaGroups -> resolve(context, mediaGroups, section).map(unused -> mediaGroups),
                MAX_RESOLVING_EMISSIONS, 1);
    }

    /**
     * @param section the sidebar section of the group built from the emission or null (e.g. search, a channel)
     */
    public static Observable<MediaGroup> resolveGroup(Context context, Observable<MediaGroup> group, BrowseSection section) {
        if (group == null) {
            return null;
        }

        return group.concatMap(mediaGroup -> resolve(context, Collections.singletonList(mediaGroup), section).map(unused -> mediaGroup));
    }

    private static Observable<Boolean> resolve(Context context, List<MediaGroup> mediaGroups, BrowseSection section) {
        // No context before the app is initialized (GlobalPreferences)
        if (context == null || mediaGroups == null) {
            return Observable.just(true);
        }

        AiSListManager aiSListManager = AiSListManager.instance(context);
        CollaborationManager collaborationManager = CollaborationManager.instance(context);
        WatchLaterManager watchLaterManager = WatchLaterManager.instance(context);
        StreamedManager streamedManager = StreamedManager.instance(context);
        Map<String, String> videoIdByKey = new LinkedHashMap<>();
        Set<String> authors = new LinkedHashSet<>();
        Set<String> streamedIds = new LinkedHashSet<>();
        boolean isAiSListUsed = false;
        boolean isWatchLaterEnabled = false;

        for (MediaGroup mediaGroup : mediaGroups) {
            if (mediaGroup == null || mediaGroup.getMediaItems() == null) {
                continue;
            }

            // The sections VideoGroup finds for the group
            int aiSListSection = VideoGroup.getAiSListSection(mediaGroup.getType(), section, mediaGroup.getChannelId());
            int filterSectionId = VideoGroup.getFilterSectionId(section, aiSListSection);
            boolean isAiSListEnabled = aiSListManager.isSectionEnabled(aiSListSection);
            boolean isCollaborationEnabled = filterSectionId != -1 && collaborationManager.isEnabled(filterSectionId);
            isWatchLaterEnabled |= filterSectionId != -1 && watchLaterManager.isEnabled(filterSectionId);
            boolean isStreamedLookedUp = filterSectionId != -1 && streamedManager.isLookedUp(filterSectionId);

            if (!isAiSListEnabled && !isCollaborationEnabled && !isStreamedLookedUp) {
                continue;
            }

            isAiSListUsed |= isAiSListEnabled;

            for (MediaItem item : mediaGroup.getMediaItems()) {
                // The card as the group sees it: the same channel name
                Video video = Video.from(item);

                // A channel card has no video to look up by: it uses the handles its name got on videos (see VideoGroup)
                if (video == null || video.videoId == null) {
                    continue;
                }

                if (isAiSListEnabled && video.channelHandle == null) {
                    String key = AiSListManager.getLookupKey(video);

                    if (key != null && !videoIdByKey.containsKey(key)) {
                        videoIdByKey.put(key, video.videoId);
                    }
                }

                String author = isCollaborationEnabled ? video.getAuthor() : null;

                if (CollaborationManager.isCandidate(author)) {
                    authors.add(author);
                }

                if (isStreamedLookedUp && StreamedManager.isCandidate(video)) {
                    streamedIds.add(video.videoId);
                }
            }
        }

        Observable<Boolean> shortsDates = ShortsDateManager.instance(context).resolve(mediaGroups);
        Observable<Boolean> streamed = streamedManager.resolve(streamedIds);
        Observable<Boolean> utubot = UtubotManager.instance(context).resolve(mediaGroups, section);

        if (!isAiSListUsed && authors.isEmpty() && !isWatchLaterEnabled) {
            return Observable.zip(shortsDates, streamed, utubot, (dates, streams, verdicts) -> true);
        }

        return Observable.zip(
                // Known handles are checked against the lists too, e.g. at the first start
                isAiSListUsed ? aiSListManager.awaitLists() : Observable.just(true),
                aiSListManager.resolveHandles(videoIdByKey),
                collaborationManager.resolve(authors),
                isWatchLaterEnabled ? watchLaterManager.resolve() : Observable.just(true),
                shortsDates,
                streamed,
                utubot,
                (lists, handles, collaborations, watchLater, dates, streams, verdicts) -> true)
                // Show the videos rather than nothing
                .onErrorReturn(error -> {
                    Log.e(TAG, "Can't resolve the hidden videos: %s", error.getMessage());
                    return true;
                });
    }
}
