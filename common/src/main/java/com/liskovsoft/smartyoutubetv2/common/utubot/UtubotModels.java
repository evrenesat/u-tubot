package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The objects of the u-tubot wire contract (ai/CONTRACT.md)
 */
public final class UtubotModels {
    public static final String STATUS_READY = "ready";
    public static final String STATUS_PENDING = "pending";
    public static final String STATUS_FAILED = "failed";
    public static final String ACTION_NONE = "none";
    public static final String ACTION_MARK = "mark";
    public static final String ACTION_HIDE = "hide";

    private UtubotModels() {
    }

    /**
     * What the app knows about a video from its card
     */
    public static final class VideoMeta {
        public String videoId;
        public String title;
        public String channel;
        public String channelId;
        public long durationSec;
        public String published;
        public String views;
        public boolean isShort;
        public boolean isLive;
        public String description;

        public JSONObject toJson() throws JSONException {
            JSONObject json = new JSONObject();
            json.put("video_id", videoId);
            putIfPresent(json, "title", title);
            putIfPresent(json, "channel", channel);
            putIfPresent(json, "channel_id", channelId);
            if (durationSec > 0) {
                json.put("duration_s", durationSec);
            }
            putIfPresent(json, "published", published);
            putIfPresent(json, "views", views);
            json.put("is_short", isShort);
            json.put("is_live", isLive);
            putIfPresent(json, "description", description);
            return json;
        }

        private static void putIfPresent(JSONObject json, String key, String value) throws JSONException {
            if (value != null && !value.isEmpty()) {
                json.put(key, value);
            }
        }
    }

    public static final class Flag {
        public String kind;
        public String label;
        public double severity;
        public String reason;
    }

    public static final class Verdict {
        public String videoId;
        public String status = STATUS_PENDING;
        public String action = ACTION_NONE;
        @Nullable public String markLabel;
        public List<Flag> flags = Collections.emptyList();
        @Nullable public String titleQuestion;
        @Nullable public String answerShort;
        public boolean insightReady;
        public boolean captionsReady;

        public boolean isReady() {
            return STATUS_READY.equals(status);
        }
    }

    public static final class Inflation {
        public long durationSec;
        public long essentialSec;
        public double ratio;
    }

    public static final class Insight {
        public String videoId;
        public String status = STATUS_PENDING;
        @Nullable public String error;
        @Nullable public String titleQuestion;
        @Nullable public String answer;
        public double answerConfidence;
        @Nullable public String summary;
        public List<String> keyPoints = Collections.emptyList();
        @Nullable public Inflation inflation;
        @Nullable public String source;

        public boolean isPending() {
            return STATUS_PENDING.equals(status);
        }

        public boolean isFailed() {
            return STATUS_FAILED.equals(status);
        }
    }

    public static final class Summary {
        public String videoId;
        public String prompt;
        public String status = STATUS_PENDING;
        @Nullable public String text;
        @Nullable public String source;
        @Nullable public String error;

        public boolean isPending() {
            return STATUS_PENDING.equals(status);
        }

        public boolean isFailed() {
            return STATUS_FAILED.equals(status);
        }
    }

    public static final class Prompt {
        public String id;
        public String key;
        public String label;
        public boolean isDefault;
    }

    public static final class PromptSet {
        public String id;
        public String name;
        public String version;
        @Nullable public String sourceUrl;
        public List<Prompt> prompts = new ArrayList<>();
    }

    public static final class PromptList {
        @Nullable public String defaultKey;
        public List<PromptSet> sets = new ArrayList<>();

        /**
         * Every prompt of every set, in the order of the sets
         */
        public List<Prompt> allPrompts() {
            List<Prompt> result = new ArrayList<>();

            for (PromptSet set : sets) {
                result.addAll(set.prompts);
            }

            return result;
        }

        @Nullable
        public Prompt find(String key) {
            for (Prompt prompt : allPrompts()) {
                if (prompt.key.equals(key)) {
                    return prompt;
                }
            }

            return null;
        }
    }

    public static final class CaptionTrack {
        public String lang;
        public String label;
        public String url;
        public int speakers;
    }

    public static final class Captions {
        public static final String STATUS_NONE = "none";
        public static final String STATUS_QUEUED = "queued";
        public static final String STATUS_RUNNING = "running";

        public String status = STATUS_NONE;
        public double progress;
        public List<CaptionTrack> tracks = Collections.emptyList();

        public boolean isReady() {
            return STATUS_READY.equals(status) && !tracks.isEmpty();
        }
    }

    public static final class Me {
        public String user;
        public boolean assess;
        public boolean insight;
        public boolean captions;
    }
}
