package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.annotation.SuppressLint;
import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SimpleMediaItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class UtubotBrowseCache {
    public static final String DIRECTORY = "utubot_browse";
    // The JSON is parsed and written on the thread that shows or saves the section: a bounded entry keeps that work short.
    public static final int MAX_ENTRY_BYTES = 512 * 1024;
    private static final String ENTRY_EXTENSION = ".json";
    private static final String TEMP_EXTENSION = ".tmp";
    private static final int CHUNK_BYTES = 4096;
    private static final String TAG = UtubotBrowseCache.class.getSimpleName();
    private static final String KEY_SECTION = "section_id";
    private static final String KEY_IDENTITY = "identity";
    private static final String KEY_LOADED_AT = "loaded_at_ms";
    private static final String KEY_GROUPS = "groups";
    private static final String KEY_ID = "id";
    private static final String KEY_TITLE = "title";
    private static final String KEY_POSITION = "position";
    private static final String KEY_TYPE = "type";
    private static final String KEY_QUEUE = "queue";
    private static final String KEY_VIDEOS = "videos";
    @SuppressLint("StaticFieldLeak")
    private static UtubotBrowseCache sInstance;
    private final File mRoot;
    private final Map<Integer, Entry> mEntries = new HashMap<>();
    private final Map<Integer, Long> mAttempts = new HashMap<>();

    public enum State {
        MISSING, FRESH, STALE
    }

    private static final class Entry {
        private final long loadedAtMs;
        private final String identity;
        private final String groupsJson;

        private Entry(long loadedAtMs, String identity, String groupsJson) {
            this.loadedAtMs = loadedAtMs;
            this.identity = identity;
            this.groupsJson = groupsJson;
        }
    }

    public UtubotBrowseCache(File root) {
        mRoot = root;
    }

    public static synchronized UtubotBrowseCache instance(Context context) {
        if (sInstance == null) {
            sInstance = new UtubotBrowseCache(new File(context.getApplicationContext().getFilesDir(), DIRECTORY));
        }

        return sInstance;
    }

    public File root() {
        return mRoot;
    }

    public synchronized State state(int sectionId, String identity, long nowMs, int minutes) {
        Entry entry = entry(sectionId, identity);

        if (entry == null) {
            return State.MISSING;
        }

        long attemptMs = mAttempts.containsKey(sectionId) ? mAttempts.get(sectionId) : 0;

        return BrowseCachePolicy.isStale(entry.loadedAtMs, attemptMs, nowMs, minutes) ? State.STALE : State.FRESH;
    }

    @Nullable
    public synchronized List<VideoGroup> groups(BrowseSection section, String identity) {
        if (section == null) {
            return null;
        }

        Entry entry = entry(section.getId(), identity);

        if (entry == null) {
            return null;
        }

        try {
            JSONArray array = new JSONArray(entry.groupsJson);
            List<VideoGroup> groups = new ArrayList<>();

            for (int i = 0; i < array.length(); i++) {
                JSONObject groupJson = array.optJSONObject(i);

                if (groupJson != null) {
                    VideoGroup group = toVideoGroup(section, groupJson);

                    if (group != null && !group.isEmpty()) {
                        groups.add(group);
                    }
                }
            }

            return groups.isEmpty() ? null : groups;
        } catch (JSONException e) {
            Log.e(TAG, "Damaged cache of section %s: %s", section.getId(), e.getMessage());
            discard(section.getId());
            return null;
        }
    }

    public synchronized void save(BrowseSection section, List<VideoGroup> groups, String identity, long nowMs) {
        if (section == null || groups == null) {
            return;
        }

        JSONArray array = toJson(groups);

        if (array.length() == 0) {
            discard(section.getId());
            mAttempts.put(section.getId(), nowMs);
            return;
        }

        try {
            JSONObject entry = new JSONObject().put(KEY_SECTION, section.getId()).put(KEY_IDENTITY, identity)
                    .put(KEY_LOADED_AT, nowMs).put(KEY_GROUPS, array);
            byte[] bytes = entry.toString().getBytes(StandardCharsets.UTF_8);

            if (bytes.length > MAX_ENTRY_BYTES) {
                Log.e(TAG, "Cache of section %s is too large: %s bytes", section.getId(), bytes.length);
                discard(section.getId());
                return;
            }

            writeAtomically(fileOf(section.getId()), bytes);
            mEntries.put(section.getId(), new Entry(nowMs, identity, array.toString()));
            mAttempts.put(section.getId(), nowMs);
        } catch (JSONException | IOException e) {
            Log.e(TAG, "Can't keep the cache of section %s: %s", section.getId(), e.getMessage());
        }
    }

    /**
     * A row's next page: the row replaces its stored copy.
     */
    public synchronized void append(BrowseSection section, VideoGroup group, String identity, long nowMs) {
        if (section == null || group == null || group.isEmpty()) {
            return;
        }

        Entry entry = entry(section.getId(), identity);
        JSONArray array = new JSONArray();

        try {
            JSONArray old = entry != null ? new JSONArray(entry.groupsJson) : null;

            for (int i = 0; old != null && i < old.length(); i++) {
                JSONObject groupJson = old.optJSONObject(i);

                if (groupJson != null && groupJson.optInt(KEY_ID, Integer.MIN_VALUE) != group.getId()) {
                    array.put(groupJson);
                }
            }

            JSONObject groupJson = toJson(group);

            if (groupJson != null) {
                array.put(groupJson);
            }

            save(section, fromJson(section, array), identity, nowMs);
        } catch (JSONException e) {
            Log.e(TAG, "Can't keep the next page of section %s: %s", section.getId(), e.getMessage());
        }
    }

    public synchronized void markAttempt(int sectionId, long nowMs) {
        mAttempts.put(sectionId, nowMs);
    }

    public synchronized void invalidate() {
        mEntries.clear();
        mAttempts.clear();

        File[] files = mRoot.listFiles();

        if (files != null) {
            for (File file : files) {
                if (!file.delete()) {
                    Log.e(TAG, "Can't delete %s", file);
                }
            }
        }
    }

    public synchronized int count() {
        return mEntries.size();
    }

    /**
     * A multi-grid's column replaces the stored column at its position; the other columns stay.
     */
    public static List<VideoGroup> mergeByPosition(@Nullable List<VideoGroup> groups, VideoGroup group) {
        List<VideoGroup> merged = groups != null ? new ArrayList<>(groups) : new ArrayList<>();

        if (group == null) {
            return merged;
        }

        for (int i = 0; i < merged.size(); i++) {
            if (merged.get(i).getPosition() == group.getPosition()) {
                merged.set(i, group);
                return merged;
            }
        }

        merged.add(group);

        return merged;
    }

    public static int findOldId(List<VideoGroup> oldGroups, VideoGroup newGroup) {
        if (oldGroups == null || newGroup == null) {
            return -1;
        }

        for (VideoGroup oldGroup : oldGroups) {
            if (Helpers.equals(oldGroup.getTitle(), newGroup.getTitle()) && oldGroup.getPosition() == newGroup.getPosition()) {
                return oldGroup.getId();
            }
        }

        for (VideoGroup oldGroup : oldGroups) {
            if (Helpers.equals(oldGroup.getTitle(), newGroup.getTitle())) {
                return oldGroup.getId();
            }
        }

        return -1;
    }

    private Entry entry(int sectionId, String identity) {
        Entry entry = mEntries.get(sectionId);

        if (entry != null && BrowseCachePolicy.matchesIdentity(entry.identity, identity)) {
            return entry;
        }

        entry = readEntry(sectionId, identity);

        if (entry != null) {
            mEntries.put(sectionId, entry);
        }

        return entry;
    }

    @Nullable
    private Entry readEntry(int sectionId, String identity) {
        File file = fileOf(sectionId);

        if (!file.isFile()) {
            return null;
        }

        try {
            JSONObject entry = new JSONObject(new String(readAll(file), StandardCharsets.UTF_8));
            String storedIdentity = entry.optString(KEY_IDENTITY, null);

            if (!BrowseCachePolicy.matchesIdentity(storedIdentity, identity)) {
                return null;
            }

            JSONArray groups = entry.optJSONArray(KEY_GROUPS);

            return groups != null ? new Entry(entry.optLong(KEY_LOADED_AT, 0), storedIdentity, groups.toString()) : null;
        } catch (IOException | JSONException e) {
            Log.e(TAG, "Damaged cache file of section %s: %s", sectionId, e.getMessage());
            if (!file.delete()) {
                Log.e(TAG, "Can't delete %s", file);
            }
            return null;
        }
    }

    private void discard(int sectionId) {
        mEntries.remove(sectionId);
        File file = fileOf(sectionId);

        if (file.isFile() && !file.delete()) {
            Log.e(TAG, "Can't delete %s", file);
        }
    }

    private File fileOf(int sectionId) {
        return new File(mRoot, sectionId + ENTRY_EXTENSION);
    }

    private static JSONArray toJson(List<VideoGroup> groups) {
        JSONArray array = new JSONArray();

        for (VideoGroup group : groups) {
            JSONObject groupJson = toJson(group);

            if (groupJson != null) {
                array.put(groupJson);
            }
        }

        return array;
    }

    @Nullable
    private static JSONObject toJson(VideoGroup group) {
        if (group == null || group.getVideos() == null || group.isEmpty()) {
            return null;
        }

        JSONArray videos = new JSONArray();

        for (Video video : group.getVideos()) {
            JSONObject videoJson = toJson(video);

            if (videoJson != null) {
                videos.put(videoJson);
            }
        }

        if (videos.length() == 0) {
            return null;
        }

        try {
            return new JSONObject().put(KEY_ID, group.getId()).put(KEY_POSITION, group.getPosition())
                    .put(KEY_TYPE, group.getType()).put(KEY_QUEUE, group.isQueue)
                    .putOpt(KEY_TITLE, group.getTitle()).put(KEY_VIDEOS, videos);
        } catch (JSONException e) {
            Log.e(TAG, "Can't serialize a row: %s", e.getMessage());
            return null;
        }
    }

    @Nullable
    private static JSONObject toJson(Video video) {
        if (video == null) {
            return null;
        }

        try {
            JSONObject json = new JSONObject()
                    .put("id", video.id)
                    .put("item_type", video.itemType)
                    .put("category", video.category)
                    .put("percent_watched", video.percentWatched)
                    .put("start_time_seconds", video.startTimeSeconds)
                    .put("start_time_ms", video.startTimeMs)
                    .put("playlist_index", video.playlistIndex)
                    .put("section_id", video.sectionId)
                    .put("category_marks", video.categoryMarks)
                    .put("ai_mark_list", video.aiMarkList)
                    .put("has_new_content", video.hasNewContent)
                    .put("is_live", video.isLive)
                    .put("is_upcoming", video.isUpcoming)
                    .put("is_unplayable", video.isUnplayable)
                    .put("is_shorts", video.isShorts)
                    .put("is_chapter", video.isChapter)
                    .put("is_movie", video.isMovie)
                    .put("is_show", video.isShow)
                    .put("is_subscribed", video.isSubscribed)
                    .put("is_remote", video.isRemote)
                    .put("is_synced", video.isSynced)
                    .put("is_live_end", video.isLiveEnd)
                    .put("is_shuffled", video.isShuffled)
                    .put("is_collaboration", video.isCollaboration)
                    .put("is_date_added", video.isDateAdded)
                    .put("in_watch_later", video.isInWatchLater)
                    .put("show_marked", video.isShowMarked)
                    .put("streamed_marked", video.isStreamedMarked)
                    .put("live_marked", video.isLiveMarked)
                    .put("top_channel_marked", video.isTopChannelMarked)
                    .put("explore_topic_marked", video.isExploreTopicMarked);

            put(json, "title", video.title);
            put(json, "de_arrow_title", video.deArrowTitle);
            put(json, "second_title", video.secondTitle);
            put(json, "description", video.description);
            put(json, "video_id", video.videoId);
            put(json, "playlist_id", video.playlistId);
            put(json, "remote_playlist_id", video.remotePlaylistId);
            put(json, "playlist_params", video.playlistParams);
            put(json, "reload_page_key", video.reloadPageKey);
            put(json, "bg_image_url", video.bgImageUrl);
            put(json, "card_image_url", video.cardImageUrl);
            put(json, "alt_card_image_url", video.altCardImageUrl);
            put(json, "author", video.author);
            put(json, "badge", video.badge);
            put(json, "preview_url", video.previewUrl);
            put(json, "channel_id", video.channelId);
            put(json, "channel_handle", video.channelHandle);
            put(json, "channel_group_id", video.channelGroupId);
            put(json, "utubot_mark", video.utubotMark);
            put(json, "search_query", video.searchQuery);
            put(json, "click_tracking_params", video.clickTrackingParams);
            put(json, "like_count", video.likeCount);
            put(json, "dislike_count", video.dislikeCount);
            put(json, "subscriber_count", video.subscriberCount);

            return json;
        } catch (JSONException e) {
            Log.e(TAG, "Can't serialize a video: %s", e.getMessage());
            return null;
        }
    }

    private static void put(JSONObject json, String key, @Nullable Object value) throws JSONException {
        if (value != null) {
            json.put(key, String.valueOf(value));
        }
    }

    private static VideoGroup toVideoGroup(BrowseSection section, JSONObject json) {
        List<Video> videos = toVideos(json.optJSONArray(KEY_VIDEOS));

        if (videos.isEmpty()) {
            return null;
        }

        VideoGroup group = VideoGroup.from(videos, section, json.optInt(KEY_POSITION, -1));

        if (json.has(KEY_ID)) {
            group.setId(json.optInt(KEY_ID));
        }
        group.setTitle(json.optString(KEY_TITLE, null));
        group.setType(json.optInt(KEY_TYPE, -1));
        group.setAction(VideoGroup.ACTION_REPLACE);
        group.isQueue = json.optBoolean(KEY_QUEUE, false);

        return group;
    }

    private static List<Video> toVideos(@Nullable JSONArray json) {
        List<Video> videos = new ArrayList<>();

        if (json == null) {
            return videos;
        }

        for (int i = 0; i < json.length(); i++) {
            JSONObject videoJson = json.optJSONObject(i);
            Video video = videoJson != null ? toVideo(videoJson) : null;

            if (video != null) {
                videos.add(video);
            }
        }

        return videos;
    }

    private static Video toVideo(JSONObject json) {
        Video video = new Video();
        video.id = json.optInt(KEY_ID, 0);
        video.itemType = json.optInt("item_type", -1);
        video.category = json.optString("category", null);
        video.percentWatched = (float) json.optDouble("percent_watched", -1);
        video.startTimeSeconds = json.optInt("start_time_seconds", 0);
        video.startTimeMs = json.optLong("start_time_ms", 0);
        video.playlistIndex = json.optInt("playlist_index", -1);
        video.sectionId = json.optInt("section_id", -1);
        video.categoryMarks = json.optInt("category_marks", 0);
        video.aiMarkList = json.optInt("ai_mark_list", -1);
        video.hasNewContent = json.optBoolean("has_new_content", false);
        video.isLive = json.optBoolean("is_live", false);
        video.isUpcoming = json.optBoolean("is_upcoming", false);
        video.isUnplayable = json.optBoolean("is_unplayable", false);
        video.isShorts = json.optBoolean("is_shorts", false);
        video.isChapter = json.optBoolean("is_chapter", false);
        video.isMovie = json.optBoolean("is_movie", false);
        video.isShow = json.optBoolean("is_show", false);
        video.isSubscribed = json.optBoolean("is_subscribed", false);
        video.isRemote = json.optBoolean("is_remote", false);
        video.isSynced = json.optBoolean("is_synced", false);
        video.isLiveEnd = json.optBoolean("is_live_end", false);
        video.isShuffled = json.optBoolean("is_shuffled", false);
        video.isCollaboration = json.optBoolean("is_collaboration", false);
        video.isDateAdded = json.optBoolean("is_date_added", false);
        video.isInWatchLater = json.optBoolean("in_watch_later", false);
        video.isShowMarked = json.optBoolean("show_marked", false);
        video.isStreamedMarked = json.optBoolean("streamed_marked", false);
        video.isLiveMarked = json.optBoolean("live_marked", false);
        video.isTopChannelMarked = json.optBoolean("top_channel_marked", false);
        video.isExploreTopicMarked = json.optBoolean("explore_topic_marked", false);
        video.title = json.optString("title", null);
        video.deArrowTitle = json.optString("de_arrow_title", null);
        video.secondTitle = json.optString("second_title", null);
        video.description = json.optString("description", null);
        video.videoId = json.optString("video_id", null);
        video.playlistId = json.optString("playlist_id", null);
        video.remotePlaylistId = json.optString("remote_playlist_id", null);
        video.playlistParams = json.optString("playlist_params", null);
        video.reloadPageKey = json.optString("reload_page_key", null);
        video.bgImageUrl = json.optString("bg_image_url", null);
        video.cardImageUrl = json.optString("card_image_url", null);
        video.altCardImageUrl = json.optString("alt_card_image_url", null);
        video.author = json.optString("author", null);
        video.badge = json.optString("badge", null);
        video.previewUrl = json.optString("preview_url", null);
        video.channelId = json.optString("channel_id", null);
        video.channelHandle = json.optString("channel_handle", null);
        video.channelGroupId = json.optString("channel_group_id", null);
        video.utubotMark = json.optString("utubot_mark", null);
        video.searchQuery = json.optString("search_query", null);
        video.clickTrackingParams = json.optString("click_tracking_params", null);
        video.likeCount = json.optString("like_count", null);
        video.dislikeCount = json.optString("dislike_count", null);
        video.subscriberCount = json.optString("subscriber_count", null);
        video.mediaItem = SimpleMediaItem.from(video);

        return video;
    }

    private static List<VideoGroup> fromJson(BrowseSection section, JSONArray array) {
        List<VideoGroup> groups = new ArrayList<>();

        for (int i = 0; i < array.length(); i++) {
            JSONObject groupJson = array.optJSONObject(i);

            if (groupJson != null) {
                VideoGroup group = toVideoGroup(section, groupJson);

                if (group != null) {
                    groups.add(group);
                }
            }
        }

        return groups;
    }

    private static void writeAtomically(File file, byte[] content) throws IOException {
        File parent = file.getParentFile();

        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("Can't create " + parent);
        }

        File temp = new File(parent, file.getName() + TEMP_EXTENSION);

        try (FileOutputStream out = new FileOutputStream(temp)) {
            out.write(content);
            out.getFD().sync();
        }

        if (!temp.renameTo(file)) {
            temp.delete();
            throw new IOException("Can't move " + temp + " to " + file);
        }
    }

    private static byte[] readAll(File file) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] chunk = new byte[CHUNK_BYTES];

        try (InputStream in = new FileInputStream(file)) {
            int read;

            while ((read = in.read(chunk)) != -1) {
                out.write(chunk, 0, read);
            }
        }

        return out.toByteArray();
    }
}
