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
    /** The video has no transcript yet; the user may have one made in the background */
    public static final String STATUS_NEEDS_TRANSCRIPT = "needs_transcript";
    public static final String TRANSCRIPT_OK = "ok";
    public static final String TRANSCRIPT_READY = "ready";
    public static final String TRANSCRIPT_NONE = "none";
    public static final String TRANSCRIPT_DELAYED = "delayed";
    public static final String TRANSCRIPT_TRANSCRIBING = "transcribing";
    public static final String TRANSCRIPT_FAILED = "failed";
    /** A field the backend did not send */
    public static final int UNKNOWN = -1;
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

    /**
     * What an answer of the backend (a summary, an insight) says about the transcript it is made from. The text is there only
     * when it is {@link #STATUS_READY}; otherwise these fields say why (see "Transcript status" of ai/CONTRACT.md). An older backend sends none.
     */
    public abstract static class Answer {
        public String status = STATUS_PENDING;
        @Nullable public String error;
        @Nullable public String source;
        /** Where the transcript stands: none, delayed, transcribing, ok or failed */
        @Nullable public String transcriptStatus;
        /** The user may have the audio transcribed (with a video without captions, or after a failed transcription) */
        public boolean canTranscribe;
        /** What the backend tells the user, e.g. why there is no summary */
        @Nullable public String message;
        /** Why a video can't be summarized (private, members_only, age_restricted, unavailable, forbidden, too_long, live): asking again changes nothing */
        @Nullable public String reason;
        public int estimateSec = UNKNOWN;
        public int retryAfterSec = UNKNOWN;
        /** Transcription progress, 0 to 100 */
        public int progressPercent = UNKNOWN;

        public boolean isReady() {
            return STATUS_READY.equals(status);
        }

        public boolean isPending() {
            return STATUS_PENDING.equals(status);
        }

        public boolean isFailed() {
            return STATUS_FAILED.equals(status);
        }

        /** No captions to summarize: the user decides on a background transcription */
        public boolean needsTranscript() {
            return STATUS_NEEDS_TRANSCRIPT.equals(status) || TRANSCRIPT_NONE.equals(transcriptStatus);
        }

        /** YouTube is slowing the backend down: ask again after {@link #retryAfterSec} */
        public boolean isDelayed() {
            return TRANSCRIPT_DELAYED.equals(transcriptStatus);
        }

        public boolean isTranscribing() {
            return TRANSCRIPT_TRANSCRIBING.equals(transcriptStatus);
        }

        /**
         * An answer of the moment: not a result. It is shown and asked for again; it is never kept (see UtubotManager).
         */
        public boolean isTransient() {
            return needsTranscript() || isDelayed() || isTranscribing();
        }
    }

    public static final class Insight extends Answer {
        public String videoId;
        @Nullable public String titleQuestion;
        @Nullable public String answer;
        public double answerConfidence;
        @Nullable public String summary;
        public List<String> keyPoints = Collections.emptyList();
        @Nullable public Inflation inflation;
    }

    public static final class Summary extends Answer {
        public String videoId;
        public String prompt;
        @Nullable public String text;
    }

    /**
     * The state of a video's transcript (`GET /v1/videos/{id}/transcript`, the answer of `POST .../transcribe`)
     */
    public static final class Transcript {
        public String videoId;
        public String status = "unknown";
        public int progressPercent = UNKNOWN;
        public int estimateSec = UNKNOWN;
        @Nullable public String error;

        public boolean isDone() {
            return TRANSCRIPT_OK.equals(status) || TRANSCRIPT_READY.equals(status);
        }

        public boolean isTranscribing() {
            return TRANSCRIPT_TRANSCRIBING.equals(status) || "queued".equals(status) || "running".equals(status);
        }

        public boolean isFailed() {
            return TRANSCRIPT_FAILED.equals(status);
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
        /**
         * The prompt of the passive side panel (the answer to prompt=panel). Null on a backend that has none.
         */
        @Nullable public String panelDefaultKey;
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

        /**
         * The first prompt of the list: what the passive panel falls back to on a backend that doesn't know prompt=panel
         */
        @Nullable
        public Prompt first() {
            List<Prompt> all = allPrompts();

            return all.isEmpty() ? null : all.get(0);
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
