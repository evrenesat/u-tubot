package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Captions;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Flag;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Inflation;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Insight;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Me;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptSet;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * JSON of the contract to the model objects. Unknown fields are ignored, missing ones keep their defaults.
 */
public final class UtubotParser {
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
        insight.status = json.optString("status", insight.status);
        insight.error = optString(json, "error");
        insight.titleQuestion = optString(json, "title_question");
        insight.answer = optString(json, "answer");
        insight.answerConfidence = json.optDouble("answer_confidence", 0);
        insight.summary = optString(json, "summary");
        insight.source = optString(json, "source");
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
        summary.status = json.optString("status", summary.status);
        summary.text = optString(json, "text");
        summary.source = optString(json, "source");
        summary.error = optString(json, "error");
        return summary;
    }

    public static PromptList parsePrompts(String body) throws JSONException {
        JSONObject json = new JSONObject(body);
        PromptList list = new PromptList();
        list.defaultKey = optString(json, "default");
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
        }

        return me;
    }

    @Nullable
    private static String optString(JSONObject json, String key) {
        return json.isNull(key) ? null : json.optString(key, null);
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
