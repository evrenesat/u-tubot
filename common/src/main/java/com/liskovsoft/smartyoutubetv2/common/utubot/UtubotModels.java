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
        public boolean cuts;
    }

    //region Director's cuts

    /** The state of a preset for a video (the picker) and of a request (the queue and the follower) */
    public static final class CutMode {
        public static final String QUICK = "quick";
        public static final String WATCHED = "watched";

        private CutMode() {
        }
    }

    public static final class CutState {
        public static final String NONE = "none";
        public static final String WAITING = "waiting";
        public static final String BUILDING = "building";
        public static final String NEEDS_TRANSCRIPT = "needs_transcript";
        public static final String READY = "ready";
        public static final String FAILED = "failed";

        private CutState() {
        }
    }

    /** A kept part of a cut, for display */
    public static final class CutPart {
        public String label;
        public long startMs;
        public long endMs;
    }

    /**
     * A cut the backend built: the parts to keep and, the other way round, the ranges the TV skips. Every time is a millisecond of
     * the video the cut was built for (see ai/CONTRACT.md).
     */
    public static final class Cut {
        public String videoId;
        /** The length the cut was built for; the TV does not apply it to a video of another length */
        public long durationMs = UNKNOWN;
        public String label;
        public String summary;
        public List<CutPart> parts = Collections.emptyList();
        /** The sorted, non-overlapping complement of {@link #parts}: [from, to] pairs */
        public List<long[]> skipRangesMs = Collections.emptyList();
        public long keptMs = UNKNOWN;
        public String transcriptHash;
        public String presetId;
        public String model;
        public String builtAt;
    }

    /** A row of the cut picker (`GET /v1/videos/{id}/cuts`): a preset and where its cut for this video stands */
    public static final class CutPreset {
        public String id;
        public String label;
        public String state = CutState.NONE;
        @Nullable public String requestId;
        @Nullable public String error;
        @Nullable public Cut cut;

        public boolean isReady() {
            return CutState.READY.equals(state) && cut != null;
        }

        /** Nothing is being built: picking the preset starts a fresh request (a failure is retried) */
        public boolean canRequest() {
            return CutState.NONE.equals(state) || CutState.FAILED.equals(state);
        }
    }

    public static final class CutList {
        public boolean configured;
        /** The mode a new cut uses here: the request, its channel, its user, then the server */
        public String defaultMode;
        /** request, channel, user or server: which of those decided {@link #defaultMode} */
        public String modeRule;
        @Nullable public String channelId;
        @Nullable public String channelName;
        /** The channel's own mode, null when it follows the user default; it wins over the user's choice */
        @Nullable public String channelMode;
        public List<CutPreset> presets = Collections.emptyList();
    }

    /** A cut request (`GET /v1/cuts/{id}`): what the phone queue shows and the TV long-polls */
    public static final class CutRequest {
        public String id;
        public String videoId;
        public String state = CutState.WAITING;
        public String source;
        public String presetId;
        public String prompt;
        public String error;
        public String title;
        public String channel;
        @Nullable public String channelId;
        /** The mode the cut is built in, and the rule that chose it: request, channel, user or server */
        public String mode;
        @Nullable public String modeRule;
        public long durationSec = UNKNOWN;
        /** Where a building request stands: transcript, model or checking */
        public String stage;
        @Nullable public Cut cut;

        public boolean isWaiting() {
            return CutState.WAITING.equals(state);
        }

        public boolean isBuilding() {
            return CutState.BUILDING.equals(state) || CutState.NEEDS_TRANSCRIPT.equals(state);
        }

        public boolean isDone() {
            return CutState.READY.equals(state) || CutState.FAILED.equals(state) || "dismissed".equals(state);
        }

        public boolean isReady() {
            return CutState.READY.equals(state) && cut != null;
        }
    }

    //endregion

    //region Processed videos

    /** The state of a caption job, as `GET /v1/jobs` and `GET /v1/processed` report it */
    public static final class JobState {
        public static final String WAITING = "waiting";
        public static final String PROCESSING = "processing";
        public static final String READY = "ready";
        public static final String FAILED = "failed";
        public static final String CANCELLED = "cancelled";

        private JobState() {
        }
    }

    /** One caption job of a processed video */
    public static final class ProcessedCaption {
        public String jobId;
        @Nullable public String lang;
        @Nullable public String translateTo;
        public String state = JobState.WAITING;
        /** 0 to 1: the backend sends a fraction, like `GET /v1/jobs` */
        public double progress;
        @Nullable public String error;
        /** Seconds since the epoch, like the contract's timestamps */
        public double createdAt;
        public double updatedAt;

        public boolean isReady() {
            return JobState.READY.equals(state);
        }
    }

    /** One cut request of a processed video */
    public static final class ProcessedCut {
        public String requestId;
        public String state = CutState.WAITING;
        @Nullable public String presetId;
        @Nullable public String presetLabel;
        @Nullable public String prompt;
        @Nullable public String error;
        /** Seconds since the epoch, like the contract's timestamps */
        public double createdAt;
        public double updatedAt;

        public boolean isReady() {
            return CutState.READY.equals(state);
        }
    }

    /** A video the caller recently processed: its caption jobs and cut requests, and whether a summary is stored */
    public static final class ProcessedItem {
        public String videoId;
        @Nullable public String title;
        @Nullable public String thumbnail;
        /** The newest change of its caption jobs and cuts, in seconds since the epoch */
        public double updatedAt;
        public boolean summary;
        public List<ProcessedCaption> captions = Collections.emptyList();
        public List<ProcessedCut> cuts = Collections.emptyList();
    }

    /** The answer of `GET /v1/processed`: one item per video, newest last change first */
    public static final class ProcessedList {
        public List<ProcessedItem> videos = Collections.emptyList();
    }

    //endregion
}
