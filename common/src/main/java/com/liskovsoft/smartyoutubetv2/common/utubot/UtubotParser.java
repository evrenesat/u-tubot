package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Flag;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Inflation;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Answer;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutMode;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPart;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutWatched;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutPreset;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CutRequest;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCaption;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedCut;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedItem;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.ProcessedList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Transcript;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/**
 * JSON of the contract to the model objects. Unknown fields are ignored, missing ones keep their defaults.
 */
public final class UtubotParser {
    private static final int PERCENT = 100;

    private UtubotParser() {
    }

    public static List<Verdict> parseAssess(String body) throws JSONException {
        JSONArray results = new JSONObject(body).optJSONArray("results");
        List<Verdict> verdicts = new ArrayList<>();

        if (results == null) {
            return verdicts;
        }

        for (int i = 0; i < results.length(); i++) {
            verdicts.add(parseVerdict(results.getJSONObject(i)));
        }

        return verdicts;
    }

    public static Verdict parseVerdict(JSONObject json) {
        Verdict verdict = new Verdict();
        verdict.videoId = json.optString("video_id", null);
        verdict.status = json.optString("status", verdict.status);
        verdict.action = json.optString("action", verdict.action);
        verdict.markLabel = optString(json, "mark_label");
        verdict.titleQuestion = optString(json, "title_question");
        verdict.answerShort = optString(json, "answer_short");
        verdict.insightReady = json.optBoolean("insight_ready");
        verdict.captionsReady = json.optBoolean("captions_ready");
        JSONArray flags = json.optJSONArray("flags");

        if (flags != null) {
            verdict.flags = new ArrayList<>();

            for (int i = 0; i < flags.length(); i++) {
                JSONObject flagJson = flags.optJSONObject(i);

                if (flagJson == null) {
                    continue;
                }

                Flag flag = new Flag();
                flag.kind = flagJson.optString("kind", null);
                flag.label = optString(flagJson, "label");
                flag.severity = flagJson.optDouble("severity", 0);
                flag.reason = optString(flagJson, "reason");
                verdict.flags.add(flag);
            }
        }

        return verdict;
    }

    public static Insight parseInsight(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        Insight insight = new Insight();
        insight.videoId = json.optString("video_id", null);
        readAnswer(json, insight);
        insight.titleQuestion = optString(json, "title_question");
        insight.answer = optString(json, "answer");
        insight.answerConfidence = json.optDouble("answer_confidence", 0);
        insight.summary = optString(json, "summary");
        insight.keyPoints = optStrings(json.optJSONArray("key_points"));
        JSONObject inflation = json.optJSONObject("inflation");

        if (inflation != null) {
            insight.inflation = new Inflation();
            insight.inflation.durationSec = inflation.optLong("duration_s");
            insight.inflation.essentialSec = inflation.optLong("essential_s");
            insight.inflation.ratio = inflation.optDouble("ratio", 0);
        }

        return insight;
    }

    public static Summary parseSummary(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        Summary summary = new Summary();
        summary.videoId = json.optString("video_id", null);
        summary.prompt = optString(json, "prompt");
        summary.text = optString(json, "text");
        readAnswer(json, summary);
        return summary;
    }

    /**
     * The fields every answer has: the status, the error, the source and what it says about the transcript
     */
    private static void readAnswer(JSONObject json, Answer answer) {
        answer.status = json.optString("status", answer.status);
        answer.error = optString(json, "error");
        answer.source = optString(json, "source");
        answer.transcriptStatus = optString(json, "transcript_status");
        // The offer comes with a video without captions; a failed answer carries it when a transcription may be tried again
        answer.canTranscribe = json.optBoolean("can_transcribe", answer.needsTranscript());
        answer.message = optString(json, "message");
        answer.reason = optString(json, "reason");
        answer.estimateSec = optSeconds(json, "estimate_s");
        answer.retryAfterSec = optSeconds(json, "retry_after_s");
        answer.progressPercent = optPercent(json, "progress");
    }

    public static Transcript parseTranscript(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        Transcript transcript = new Transcript();
        transcript.videoId = json.optString("video_id", null);
        String status = optString(json, "transcript_status");
        transcript.status = status != null ? status : json.optString("status", transcript.status);
        transcript.progressPercent = optPercent(json, "progress");
        transcript.estimateSec = optSeconds(json, "estimate_s");
        transcript.error = optString(json, "error");
        return transcript;
    }

    public static PromptList parsePrompts(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        PromptList list = new PromptList();
        list.defaultKey = optString(json, "default");
        list.panelDefaultKey = optString(json, "panel_default");
        JSONArray sets = json.optJSONArray("sets");

        if (sets == null) {
            return list;
        }

        for (int i = 0; i < sets.length(); i++) {
            list.sets.add(parsePromptSet(sets.getJSONObject(i)));
        }

        return list;
    }

    public static PromptSet parsePromptSet(JSONObject json) {
        PromptSet set = new PromptSet();
        set.id = json.optString("id", null);
        set.name = json.optString("name", set.id);
        set.version = optString(json, "version");
        set.sourceUrl = optString(json, "source_url");
        JSONArray prompts = json.optJSONArray("prompts");

        if (prompts == null) {
            return set;
        }

        for (int i = 0; i < prompts.length(); i++) {
            JSONObject promptJson = prompts.optJSONObject(i);

            if (promptJson == null) {
                continue;
            }

            Prompt prompt = new Prompt();
            prompt.id = promptJson.optString("id", null);
            prompt.key = promptJson.optString("key", set.id + "/" + prompt.id);
            prompt.label = promptJson.optString("label", prompt.id);
            prompt.isDefault = promptJson.optBoolean("default");
            set.prompts.add(prompt);
        }

        return set;
    }

    public static PromptSet parseImportedSet(String body) throws JSONException {
        return parsePromptSet(new JSONObject(body));
    }

    public static Captions parseCaptions(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        Captions captions = new Captions();
        captions.status = json.optString("status", captions.status);
        captions.progress = json.optDouble("progress", 0);
        JSONArray tracks = json.optJSONArray("tracks");

        if (tracks != null) {
            captions.tracks = new ArrayList<>();

            for (int i = 0; i < tracks.length(); i++) {
                JSONObject trackJson = tracks.optJSONObject(i);

                if (trackJson == null) {
                    continue;
                }

                CaptionTrack track = new CaptionTrack();
                track.lang = trackJson.optString("lang", null);
                track.label = trackJson.optString("label", track.lang);
                track.url = trackJson.optString("url", null);
                track.speakers = trackJson.optInt("speakers");

                if (track.url != null) {
                    captions.tracks.add(track);
                }
            }
        }

        return captions;
    }

    public static Me parseMe(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        Me me = new Me();
        me.user = json.optString("user", null);
        JSONObject features = json.optJSONObject("features");

        if (features != null) {
            me.assess = features.optBoolean("assess");
            me.insight = features.optBoolean("insight");
            me.captions = features.optBoolean("captions");
            me.cuts = features.optBoolean("cuts");
        }

        return me;
    }

    //region Director's cuts

    public static CutList parseCuts(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        CutList list = new CutList();
        list.configured = json.optBoolean("configured");
        list.defaultMode = json.optString("default_mode", CutMode.QUICK);
        JSONArray modes = json.optJSONArray("modes");

        if (modes != null) {
            List<CutMode> parsedModes = new ArrayList<>();

            for (int i = 0; i < modes.length(); i++) {
                JSONObject modeJson = modes.optJSONObject(i);

                if (modeJson == null) {
                    continue;
                }

                CutMode mode = new CutMode();
                mode.id = modeJson.optString("id", null);
                mode.label = modeJson.optString("label", mode.id);
                mode.defaultMode = modeJson.optBoolean("default");
                mode.available = modeJson.optBoolean("available", true);
                mode.reason = optString(modeJson, "reason");
                mode.etaSec = optSeconds(modeJson, "eta_s");
                if (mode.id != null) {
                    parsedModes.add(mode);
                }
            }

            list.modes = parsedModes;
        }

        JSONArray presets = json.optJSONArray("presets");

        if (presets != null) {
            List<CutPreset> parsed = new ArrayList<>();

            for (int i = 0; i < presets.length(); i++) {
                JSONObject presetJson = presets.optJSONObject(i);

                if (presetJson == null) {
                    continue;
                }

                String id = presetJson.optString("id", null);
                String label = presetJson.optString("label", id);
                CutPreset preset = parsePresetState(presetJson, id, label);
                JSONObject byMode = presetJson.optJSONObject("by_mode");

                if (byMode != null) {
                    Map<String, CutPreset> parsedByMode = new HashMap<>();
                    Iterator<String> modeIds = byMode.keys();
                    while (modeIds.hasNext()) {
                        String modeId = modeIds.next();
                        JSONObject modeJson = byMode.optJSONObject(modeId);
                        if (modeJson != null) {
                            parsedByMode.put(modeId, parsePresetState(modeJson, id, label));
                        }
                    }
                    preset.byMode = parsedByMode;
                }

                if (preset.id != null) {
                    parsed.add(preset);
                }
            }

            list.presets = parsed;
        }

        return list;
    }

    private static CutPreset parsePresetState(JSONObject json, @Nullable String id, @Nullable String label) {
        CutPreset preset = new CutPreset();
        preset.id = id;
        preset.label = label != null ? label : id;
        preset.state = json.optString("state", UtubotModels.CutState.NONE);
        preset.requestId = optString(json, "request_id");
        preset.error = optString(json, "error");
        preset.cut = parseCut(json.optJSONObject("cut"));
        return preset;
    }

    public static CutRequest parseCutRequest(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        CutRequest request = new CutRequest();
        // the answer of a create is {"request_id", ...}, the request document carries "id"
        request.id = optString(json, "request_id");
        request.id = request.id != null ? request.id : json.optString("id", null);
        request.videoId = json.optString("video_id", null);
        request.state = json.optString("state", request.state);
        request.source = optString(json, "source");
        request.presetId = optString(json, "preset_id");
        request.prompt = optString(json, "prompt");
        request.error = optString(json, "error");
        request.title = optString(json, "title");
        request.channel = optString(json, "channel");
        request.durationSec = optSeconds(json, "duration_s") == UtubotModels.UNKNOWN ? UtubotModels.UNKNOWN : json.optLong("duration_s", UtubotModels.UNKNOWN);
        request.mode = json.optString("mode", CutMode.QUICK);
        request.etaSec = optSeconds(json, "eta_s");
        request.stage = optString(json, "stage");
        request.cut = parseCut(json.optJSONObject("cut"));
        return request;
    }

    @Nullable
    public static Cut parseCut(@Nullable JSONObject json) {
        if (json == null) {
            return null;
        }

        Cut cut = new Cut();
        cut.videoId = json.optString("video_id", null);
        cut.durationMs = json.optLong("duration_ms", UtubotModels.UNKNOWN);
        cut.label = optString(json, "label");
        cut.summary = optString(json, "summary");
        cut.keptMs = json.optLong("kept_ms", UtubotModels.UNKNOWN);
        cut.transcriptHash = optString(json, "transcript_hash");
        cut.presetId = optString(json, "preset_id");
        cut.model = optString(json, "model");
        cut.mode = json.optString("mode", CutMode.QUICK);
        JSONObject watchedJson = json.optJSONObject("watched");
        if (watchedJson != null) {
            CutWatched watched = new CutWatched();
            watched.grids = watchedJson.optInt("grids", UtubotModels.UNKNOWN);
            watched.model = optString(watchedJson, "model");
            watched.partial = watchedJson.optBoolean("partial");
            watched.coarse = watchedJson.optBoolean("coarse");
            cut.watched = watched;
        }
        cut.builtAt = optString(json, "built_at");
        cut.parts = parseParts(json.optJSONArray("parts"));
        cut.skipRangesMs = parseSkipRanges(json.optJSONArray("skip_ranges_ms"));
        return cut;
    }

    private static List<CutPart> parseParts(@Nullable JSONArray array) {
        if (array == null) {
            return Collections.emptyList();
        }

        List<CutPart> parts = new ArrayList<>();

        for (int i = 0; i < array.length(); i++) {
            JSONObject partJson = array.optJSONObject(i);

            if (partJson == null) {
                continue;
            }

            CutPart part = new CutPart();
            part.label = optString(partJson, "label");
            part.startMs = partJson.optLong("start_ms", 0);
            part.endMs = partJson.optLong("end_ms", 0);
            parts.add(part);
        }

        return parts;
    }

    private static List<long[]> parseSkipRanges(@Nullable JSONArray array) {
        if (array == null) {
            return Collections.emptyList();
        }

        List<long[]> ranges = new ArrayList<>();

        for (int i = 0; i < array.length(); i++) {
            JSONArray range = array.optJSONArray(i);

            if (range != null && range.length() >= 2) {
                ranges.add(new long[]{range.optLong(0), range.optLong(1)});
            }
        }

        return ranges;
    }

    //endregion

    //region Processed videos

    /**
     * The caller's recently processed videos (`GET /v1/processed`): one item per video, newest first
     */
    public static ProcessedList parseProcessed(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        ProcessedList list = new ProcessedList();
        JSONArray videos = json.optJSONArray("videos");

        if (videos != null) {
            List<ProcessedItem> parsed = new ArrayList<>();

            for (int i = 0; i < videos.length(); i++) {
                JSONObject videoJson = videos.optJSONObject(i);

                if (videoJson == null) {
                    continue;
                }

                String videoId = videoJson.optString("video_id", null);

                if (videoId == null) {
                    continue;
                }

                ProcessedItem item = new ProcessedItem();
                item.videoId = videoId;
                item.title = optString(videoJson, "title");
                item.thumbnail = optString(videoJson, "thumbnail");
                item.updatedAt = videoJson.optDouble("updated_at", 0);
                item.summary = videoJson.optBoolean("summary");
                item.captions = parseProcessedCaptions(videoJson.optJSONArray("captions"));
                item.cuts = parseProcessedCuts(videoJson.optJSONArray("cuts"));
                parsed.add(item);
            }

            list.videos = parsed;
        }

        return list;
    }

    private static List<ProcessedCaption> parseProcessedCaptions(@Nullable JSONArray array) {
        if (array == null) {
            return Collections.emptyList();
        }

        List<ProcessedCaption> captions = new ArrayList<>();

        for (int i = 0; i < array.length(); i++) {
            JSONObject json = array.optJSONObject(i);

            if (json == null) {
                continue;
            }

            String jobId = json.optString("job_id", null);

            if (jobId == null) {
                continue;
            }

            ProcessedCaption caption = new ProcessedCaption();
            caption.jobId = jobId;
            caption.lang = optString(json, "lang");
            caption.translateTo = optString(json, "translate_to");
            caption.state = json.optString("state", caption.state);
            caption.progress = json.optDouble("progress", caption.progress);
            caption.error = optString(json, "error");
            caption.createdAt = json.optDouble("created_at", caption.createdAt);
            caption.updatedAt = json.optDouble("updated_at", caption.updatedAt);
            captions.add(caption);
        }

        return captions;
    }

    private static List<ProcessedCut> parseProcessedCuts(@Nullable JSONArray array) {
        if (array == null) {
            return Collections.emptyList();
        }

        List<ProcessedCut> cuts = new ArrayList<>();

        for (int i = 0; i < array.length(); i++) {
            JSONObject json = array.optJSONObject(i);

            if (json == null) {
                continue;
            }

            String requestId = optString(json, "request_id");

            if (requestId == null) {
                continue;
            }

            ProcessedCut cut = new ProcessedCut();
            cut.requestId = requestId;
            cut.state = json.optString("state", cut.state);
            cut.mode = json.optString("mode", CutMode.QUICK);
            cut.presetId = optString(json, "preset_id");
            cut.presetLabel = optString(json, "preset_label");
            cut.prompt = optString(json, "prompt");
            cut.error = optString(json, "error");
            cut.createdAt = json.optDouble("created_at", cut.createdAt);
            cut.updatedAt = json.optDouble("updated_at", cut.updatedAt);
            cuts.add(cut);
        }

        return cuts;
    }

    //endregion

    @Nullable
    private static String optString(JSONObject json, String key) {
        return json.isNull(key) ? null : json.optString(key, null);
    }

    /**
     * @return the whole seconds of a number field, {@link UtubotModels#UNKNOWN} when it is missing, null or not a positive number
     */
    private static int optSeconds(JSONObject json, String key) {
        double value = json.isNull(key) ? Double.NaN : json.optDouble(key, Double.NaN);

        return Double.isNaN(value) || value <= 0 ? UtubotModels.UNKNOWN : (int) Math.ceil(value);
    }

    /**
     * @return a progress as 0 to 100: the backend sends a fraction (0.0 to 1.0); a number above 1 is taken as a percentage already
     */
    private static int optPercent(JSONObject json, String key) {
        double value = json.isNull(key) ? Double.NaN : json.optDouble(key, Double.NaN);

        if (Double.isNaN(value) || value < 0) {
            return UtubotModels.UNKNOWN;
        }

        double percent = value <= 1.0 ? value * PERCENT : value;

        return (int) Math.min(PERCENT, Math.round(percent));
    }

    private static List<String> optStrings(@Nullable JSONArray array) {
        List<String> result = new ArrayList<>();

        if (array != null) {
            for (int i = 0; i < array.length(); i++) {
                result.add(array.optString(i));
            }
        }

        return result;
    }
}
