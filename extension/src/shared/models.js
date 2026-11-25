/**
 * JSON of the wire contract (ai/CONTRACT.md) to plain model objects. Unknown fields are ignored, missing ones keep
 * their defaults. The field names follow the contract; `progress` is kept as the contract's fraction and
 * `progressPercent` is the 0-100 form the TV's words use.
 */

const UNKNOWN = -1;

function text(json, key) {
  const value = json?.[key];
  return value === null || value === undefined || value === "" ? null : String(value);
}

function percent(value) {
  if (typeof value !== "number") {
    return UNKNOWN;
  }

  return Math.round(value * 100);
}

function seconds(value) {
  if (typeof value !== "number") {
    return UNKNOWN;
  }

  return Math.round(value);
}

function strings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
}

function attachHelpers(target, values) {
  for (const [name, value] of Object.entries(values)) {
    Object.defineProperty(target, name, { value, enumerable: false, configurable: true });
  }
  return target;
}

export function parseVerdict(json) {
  return {
    videoId: json?.video_id ?? null,
    status: json?.status ?? "pending",
    action: json?.action ?? "none",
    markLabel: text(json, "mark_label"),
    flags: Array.isArray(json?.flags) ? json.flags : [],
    titleQuestion: text(json, "title_question"),
    answerShort: text(json, "answer_short"),
    insightReady: Boolean(json?.insight_ready),
    captionsReady: Boolean(json?.captions_ready),
  };
}

export function parseAssess(answer) {
  const results = Array.isArray(answer?.results) ? answer.results : [];
  return results.map(parseVerdict);
}

function readAnswer(json, answer) {
  answer.status = json?.status ?? "pending";
  answer.error = text(json, "error");
  answer.source = text(json, "source");
  answer.transcriptStatus = text(json, "transcript_status");
  answer.canTranscribe = typeof json?.can_transcribe === "boolean"
    ? json.can_transcribe
    : answer.status === "needs_transcript" || answer.transcriptStatus === "none";
  answer.message = text(json, "message");
  answer.reason = text(json, "reason");
  answer.estimateSec = seconds(json?.estimate_s);
  answer.retryAfterSec = seconds(json?.retry_after_s);
  answer.progress = typeof json?.progress === "number" ? json.progress : UNKNOWN;
  answer.progressPercent = percent(json?.progress);
  return answer;
}

export function reviveAnswer(answer) {
  return attachHelpers(answer, {
    isReady: () => answer.status === "ready",
    isPending: () => answer.status === "pending",
    isFailed: () => answer.status === "failed",
    needsTranscript: () => answer.status === "needs_transcript" || answer.transcriptStatus === "none",
    isDelayed: () => answer.transcriptStatus === "delayed",
    isTranscribing: () => answer.transcriptStatus === "transcribing",
    isTransient: () => answer.status === "needs_transcript" || answer.transcriptStatus === "none"
      || answer.transcriptStatus === "delayed" || answer.transcriptStatus === "transcribing",
  });
}

export function parseInsight(json) {
  return readAnswer(json, {
    videoId: json?.video_id ?? null,
    titleQuestion: text(json, "title_question"),
    answer: text(json, "answer"),
    answerConfidence: typeof json?.answer_confidence === "number" ? json.answer_confidence : 0,
    summary: text(json, "summary"),
    keyPoints: strings(json?.key_points),
    inflation: json?.inflation ?? null,
  });
}

export function parseSummary(json) {
  return readAnswer(json, {
    videoId: json?.video_id ?? null,
    prompt: text(json, "prompt"),
    text: text(json, "text"),
  });
}

export function parseTranscript(json) {
  const status = text(json, "transcript_status") ?? json?.status ?? "unknown";
  return {
    videoId: json?.video_id ?? null,
    status,
    progressPercent: percent(json?.progress),
    progress: typeof json?.progress === "number" ? json.progress : UNKNOWN,
    estimateSec: seconds(json?.estimate_s),
    error: text(json, "error"),
  };
}

export function reviveTranscript(transcript) {
  return attachHelpers(transcript, {
    isDone: () => transcript.status === "ok" || transcript.status === "ready",
    isTranscribing: () => transcript.status === "transcribing" || transcript.status === "queued" || transcript.status === "running",
    isFailed: () => transcript.status === "failed",
  });
}

export function parsePromptSet(json, fallbackId = null) {
  const set = {
    id: json?.id ?? fallbackId,
    name: text(json, "name") ?? json?.id ?? fallbackId,
    version: text(json, "version"),
    sourceUrl: text(json, "source_url"),
    prompts: [],
  };
  for (const promptJson of Array.isArray(json?.prompts) ? json.prompts : []) {
    const id = promptJson?.id ?? null;
    set.prompts.push({
      id,
      key: promptJson?.key ?? `${set.id}/${id}`,
      label: promptJson?.label ?? id,
      isDefault: Boolean(promptJson?.default),
      isPanelDefault: Boolean(promptJson?.panel_default),
    });
  }
  return set;
}

export function parsePrompts(json) {
  return {
    defaultKey: text(json, "default"),
    panelDefaultKey: text(json, "panel_default"),
    sets: (Array.isArray(json?.sets) ? json.sets : []).map((set) => parsePromptSet(set)),
  };
}

export function revivePrompts(list) {
  const allPrompts = () => list.sets.flatMap((set) => set.prompts);
  return attachHelpers(list, {
    allPrompts,
    first: () => allPrompts()[0] ?? null,
    find: (key) => allPrompts().find((prompt) => prompt.key === key) ?? null,
  });
}

export function parseCaptions(json) {
  return {
    status: json?.status ?? "none",
    progress: typeof json?.progress === "number" ? json.progress : 0,
    tracks: (Array.isArray(json?.tracks) ? json.tracks : [])
      .filter((track) => typeof track?.url === "string")
      .map((track) => ({
        lang: track.lang ?? null,
        label: track.label ?? track.lang ?? null,
        url: track.url,
        speakers: Number(track.speakers) || 0,
        timingVersion: track.timing_version ?? null,
      })),
  };
}

export function reviveCaptions(captions) {
  return attachHelpers(captions, {
    isReady: () => captions.status === "ready" && captions.tracks.length > 0,
  });
}

export function parseMe(json) {
  const features = json?.features ?? {};
  return {
    user: text(json, "user"),
    assess: Boolean(features.assess),
    insight: Boolean(features.insight),
    captions: Boolean(features.captions),
    cuts: Boolean(features.cuts),
    settingsVersion: Number(json?.settings_version) || 0,
  };
}

export const CutState = {
  NONE: "none",
  WAITING: "waiting",
  BUILDING: "building",
  NEEDS_TRANSCRIPT: "needs_transcript",
  READY: "ready",
  FAILED: "failed",
};

export function parseCut(json) {
  if (!json) {
    return null;
  }

  return {
    videoId: json.video_id ?? null,
    durationMs: Number(json.duration_ms) || UNKNOWN,
    label: text(json, "label"),
    summary: text(json, "summary"),
    parts: (Array.isArray(json.parts) ? json.parts : []).map((part) => ({
      label: text(part, "label"),
      startMs: Number(part.start_ms) || 0,
      endMs: Number(part.end_ms) || 0,
    })),
    skipRangesMs: (Array.isArray(json.skip_ranges_ms) ? json.skip_ranges_ms : [])
      .map((range) => [Number(range?.[0]) || 0, Number(range?.[1]) || 0]),
    keptMs: Number(json.kept_ms) || UNKNOWN,
    transcriptHash: text(json, "transcript_hash"),
    presetId: text(json, "preset_id"),
    model: text(json, "model"),
    builtAt: text(json, "built_at"),
  };
}

export function parseCuts(json) {
  return {
    configured: Boolean(json?.configured),
    presets: (Array.isArray(json?.presets) ? json.presets : [])
      .filter((preset) => preset?.id)
      .map((preset) => ({
        id: preset.id,
        label: preset.label ?? preset.id,
        state: preset.state ?? CutState.NONE,
        requestId: text(preset, "request_id"),
        error: text(preset, "error"),
        cut: parseCut(preset.cut),
      })),
  };
}

export function reviveCuts(cuts) {
  for (const preset of cuts.presets) {
    attachHelpers(preset, {
      isReady: () => preset.state === CutState.READY && Boolean(preset.cut),
    });
  }
  return cuts;
}

export function parseCutRequest(json) {
  const request = {
    id: text(json, "request_id") ?? text(json, "id"),
    videoId: json?.video_id ?? null,
    state: json?.state ?? CutState.WAITING,
    source: text(json, "source"),
    presetId: text(json, "preset_id"),
    prompt: text(json, "prompt"),
    error: text(json, "error"),
    title: text(json, "title"),
    channel: text(json, "channel"),
    durationSec: typeof json?.duration_s === "number" ? json.duration_s : UNKNOWN,
    stage: text(json, "stage"),
    cut: parseCut(json?.cut),
  };
  return request;
}

export function reviveCutRequest(request) {
  return attachHelpers(request, {
    isWaiting: () => request.state === CutState.WAITING,
    isBuilding: () => request.state === CutState.BUILDING || request.state === CutState.NEEDS_TRANSCRIPT,
    isDone: () => request.state === CutState.READY || request.state === CutState.FAILED || request.state === "dismissed",
    isReady: () => request.state === CutState.READY && Boolean(request.cut),
  });
}

function parseProcessedCaptions(list) {
  return (Array.isArray(list) ? list : [])
    .filter((json) => json?.job_id)
    .map((json) => ({
      jobId: json.job_id,
      lang: text(json, "lang"),
      translateTo: text(json, "translate_to"),
      state: json.state ?? "waiting",
      progress: typeof json.progress === "number" ? json.progress : 0,
      error: text(json, "error"),
      createdAt: Number(json.created_at) || 0,
      updatedAt: Number(json.updated_at) || 0,
    }));
}

function parseProcessedCuts(list) {
  return (Array.isArray(list) ? list : [])
    .filter((json) => json?.request_id)
    .map((json) => ({
      requestId: json.request_id,
      state: json.state ?? CutState.WAITING,
      presetId: text(json, "preset_id"),
      presetLabel: text(json, "preset_label"),
      prompt: text(json, "prompt"),
      error: text(json, "error"),
      createdAt: Number(json.created_at) || 0,
      updatedAt: Number(json.updated_at) || 0,
    }));
}

export function parseProcessed(json) {
  const videos = (Array.isArray(json?.videos) ? json.videos : [])
    .filter((item) => item?.video_id)
    .map((item) => ({
      videoId: item.video_id,
      title: text(item, "title"),
      thumbnail: text(item, "thumbnail"),
      updatedAt: Number(item.updated_at) || 0,
      summary: Boolean(item.summary),
      captions: parseProcessedCaptions(item.captions),
      cuts: parseProcessedCuts(item.cuts),
    }));
  return { videos };
}

export function reviveProcessed(processed) {
  for (const video of processed.videos) {
    for (const caption of video.captions) {
      attachHelpers(caption, { isReady: () => caption.state === "ready" });
    }
    for (const cut of video.cuts) {
      attachHelpers(cut, { isReady: () => cut.state === CutState.READY });
    }
  }
  return processed;
}

export function reviveVerdict(verdict) {
  return attachHelpers(verdict, { isReady: () => verdict.status === "ready" });
}

const REVIVERS = {
  assess: (values) => values.map(reviveVerdict),
  summary: reviveAnswer,
  insight: reviveAnswer,
  transcribe: reviveTranscript,
  transcript: reviveTranscript,
  "prompts.list": revivePrompts,
  "captions.status": reviveCaptions,
  "cuts.list": reviveCuts,
  "cuts.request": reviveCutRequest,
  "cuts.follow": reviveCutRequest,
  processed: reviveProcessed,
};

export function revive(type, value) {
  return REVIVERS[type]?.(value) ?? value;
}

export { UNKNOWN };
