// Words for the job report: stage names, one-line summaries of an event's detail, and the folding of
// "running" events into the event that finished them. Pure functions, no DOM, so they stay easy to check.

export const STAGE_LABELS = {
  queued: "Queued",
  promoted: "Moved up the queue",
  started: "Picked up by a worker",
  gate_wait: "Waited for YouTube's gate",
  caption_recheck: "Caption recheck",
  audio_download: "Audio download",
  media_archive: "Media archive",
  ffmpeg: "Audio conversion",
  chunking: "Chunking",
  asr: "Speech to text",
  asr_chunk: "Chunk recognised",
  asr_fallback: "Engine fallback",
  stitching: "Stitching",
  separation: "Vocal separation",
  align: "Alignment",
  proofread: "Proofreading",
  proofread_batch: "Proofread batch",
  diarization: "Speaker labels",
  cues: "Subtitle cues",
  text: "Transcript text",
  translate: "Translation",
  stored: "Result stored",
  retry: "Retry",
  finished: "Finished",
  failed: "Failed",
  delivered: "Delivered",
};

export const VIA_LABELS = {
  vtt: "the .vtt track",
  captions_status: "the captions list",
  transcript_status: "the transcript status",
  summary: "a summary",
  summary_panel: "the panel summary",
  insight: "the insight",
  answer: "an answer",
  transcript_txt: "the transcript text",
};

const TRIGGER_MODES = { on_open: "on open", on_dwell: "on dwell" };
const REASONS = {
  unhealthy: "marked unhealthy",
  transport_timeout: "timed out",
  transport_connect: "could not connect",
  transport_error: "network error",
  not_json: "answered something that is not JSON",
  bad_shape: "answered an unexpected shape",
  not_installed: "not installed",
  language_mismatch: "audio outside its languages",
  restart: "the server restarted",
  requested: "requested by the owner",
  rate_limited: "YouTube rate limit",
  bot_check: "YouTube bot check",
  forbidden: "YouTube refused",
  network: "network error",
  cooldown: "YouTube cooldown",
  too_long: "the video is longer than the transcription limit",
  live: "live streams cannot be transcribed",
  private: "private video",
  members_only: "members-only video",
  age_restricted: "age-restricted video",
  unavailable: "video unavailable",
  empty_response: "YouTube answered with nothing",
  empty_track: "the caption file was empty",
  incomplete_response: "YouTube answered only in part",
  PipelineError: "the pipeline stopped",
  ASRError: "no speech engine could do it",
  engines_unavailable: "no speech engine available",
  no_llm: "no LLM model configured",
  unavailable: "no output",
};
const TRACKS = {
  original: "original track",
  unmarked: "single track",
  dubbed: "dubbed track (not the original)",
  descriptive: "audio-description track",
};

export function stageLabel(stage) {
  return STAGE_LABELS[stage] || stage;
}

export function reasonText(reason) {
  if (!reason) return "";
  const http = /^http_(\d+)$/.exec(reason);
  if (http) return "HTTP " + http[1];
  return REASONS[reason] || String(reason).replace(/_/g, " ");
}

export function fmtSecs(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const s = Number(seconds);
  if (s < 1) return Math.round(s * 1000) + " ms";
  if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + " s";
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  if (m < 60) return m + " min " + rest + " s";
  return Math.floor(m / 60) + " h " + (m % 60) + " min";
}

export function fmtOffset(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return "+" + Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

export function fmtBytes(n) {
  if (n === null || n === undefined) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

export function fmtClock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  return m + ":" + String(s % 60).padStart(2, "0");
}

function num(n) {
  return Number(n || 0).toLocaleString("en-US");
}

export function triggerText(trigger) {
  if (!trigger || trigger.kind === "explicit") return "asked for explicitly";
  if (trigger.kind === "auto") {
    const mode = TRIGGER_MODES[trigger.mode] || trigger.mode;
    const where = trigger.passive ? ", from the side panel" : "";
    const limit = trigger.max_minutes ? ", videos up to " + trigger.max_minutes + " min" : "";
    return "started automatically by the transcript policy (" + mode + where + limit + ")";
  }
  return String(trigger.kind);
}

function join(parts) {
  return parts.filter((p) => p !== null && p !== undefined && p !== "").join(", ");
}

const DESCRIBERS = {
  queued(d) {
    if (d.synthetic) return d.message;
    return join([
      "Requested by " + (d.user || "someone") + (d.client ? " on " + d.client : ""),
      triggerText(d.trigger),
      d.priority + " priority",
    ]);
  },
  promoted: (d) => d.message,
  started: (d) => join(["Attempt " + d.attempt, "waited " + fmtSecs(d.waited_s) + " in the queue"]),
  gate_wait: (d) => join(["Class " + d.klass, "waited " + fmtSecs(d.waited_s), d.priority + " priority"]),
  caption_recheck(d) {
    if (d.message) return d.message;
    if (d.result === "found") return "Captions exist (" + d.source + ", " + num(d.chars) + " characters); the audio was not needed";
    if (d.result === "no_captions") return "YouTube still has no captions for this video";
    return join([d.result, reasonText(d.reason)]);
  },
  audio_download(d, status) {
    if (status === "running") return d.source === "from_archive" ? "Reading the audio from the media archive" : "Downloading the audio";
    if (status === "failed") return join(["Download failed", reasonText(d.error_class)]);
    return join([
      d.source === "from_archive" ? "From the media archive" : "Downloaded",
      d.format_id ? "format " + d.format_id : null,
      d.track ? TRACKS[d.track] || d.track : null,
      d.language ? "language " + d.language : null,
      d.codec && d.codec !== "none" ? d.codec : null,
      d.bytes !== null && d.bytes !== undefined ? fmtBytes(d.bytes) : null,
      d.duration_s ? fmtClock(d.duration_s) + " of audio" : null,
    ]);
  },
  ffmpeg(d, status) {
    if (status === "running") return "Converting to 16 kHz mono";
    if (status === "failed") return "Conversion failed";
    return join([fmtClock(d.audio_s || 0) + " of audio", d.bytes ? fmtBytes(d.bytes) : null]);
  },
  media_archive(d, status) {
    if (status === "running") return "Storing the download in the media archive";
    if (status === "failed") return join(["Not kept in the media archive", reasonText(d.error_class)]);
    return join(["Kept in the media archive", d.bytes ? fmtBytes(d.bytes) : null, d.sha256 ? "sha256 " + d.sha256 + "…" : null]);
  },
  chunking(d) {
    const sizes = (d.sizes_s || []).map((s) => Math.round(s) + " s").join(", ");
    return join([d.chunks + (d.chunks === 1 ? " chunk" : " chunks") + (sizes ? " (" + sizes + ")" : ""), "engines: " + (d.engines || []).join(", ")]);
  },
  asr(d, status) {
    if (status === "running") return "Requested language: " + (d.requested_language || "auto-detect");
    if (status === "failed") return join(["Recognition failed", reasonText(d.error_class)]);
    return join([d.engine ? d.engine + " (" + d.model + ")" : null, num(d.chars) + " characters", d.language ? "language " + d.language : "language not reported"]);
  },
  asr_chunk(d, status) {
    const span = Math.round(d.start_s) + "-" + Math.round(d.end_s) + " s";
    if (status === "failed") return join([d.engine + " failed " + span, reasonText(d.error_class)]);
    return join([d.engine + " " + span, num(d.chars) + " characters", d.language ? "language " + d.language : null]);
  },
  asr_fallback(d) {
    const span = Math.round(d.start_s) + "-" + Math.round(d.end_s) + " s";
    const why = d.reason === "language_mismatch" && d.detected ? "heard " + d.detected + ", outside its languages" : reasonText(d.reason);
    return d.engine + " gave up on " + span + " (" + why + ")" + (d.next ? ", trying " + d.next : ", no engine left");
  },
  stitching(d, status) {
    if (status === "skipped") return "One chunk, nothing to join";
    return join([d.seams + (d.seams === 1 ? " seam" : " seams"), num(d.cut_segments) + " segments cut at overlaps", num(d.repeated_words) + " repeated words dropped"]);
  },
  diarization(d, status) {
    if (status === "running") return "Looking for speakers";
    if (status === "skipped") return "Skipped: " + (d.message || reasonText(d.reason));
    return num(d.turns) + " speaker turns, " + num(d.speakers) + (d.speakers === 1 ? " speaker" : " speakers");
  },
  separation(d, status) {
    if (status === "running") return "Separating the vocals from the music";
    if (status === "skipped") return "Skipped: " + (d.message || reasonText(d.reason));
    return join(["Vocals kept", d.bytes ? fmtBytes(d.bytes) : null, d.audio_s ? fmtClock(d.audio_s) + " of audio" : null]);
  },
  align(d) {
    if (d.mode === "merge") {
      return join([num(d.from_asr) + " of " + num(d.cues) + " cues re-timed from speech recognition", d.margin_s ? "window " + d.margin_s + " s" : null]);
    }
    return join([num(d.silences) + " silences found", num(d.moved) + " boundaries moved"]);
  },
  proofread(d, status) {
    if (status === "running") return join([num(d.cues) + " cues in " + d.batches + " batch" + (d.batches === 1 ? "" : "es"), d.language ? "language " + d.language : null]);
    if (status === "skipped") return "Skipped: " + (d.message || reasonText(d.reason));
    return join([num(d.corrected) + " of " + num(d.cues) + " cues corrected", d.warned ? d.warned + " batch" + (d.warned === 1 ? "" : "es") + " not proofread" : null, d.cached ? "from the stage cache" : null, num(d.chars_in) + " → " + num(d.chars_out) + " characters"]);
  },
  proofread_batch(d, status) {
    if (status === "failed" || status === "warn") return join(["Batch " + d.batch + " kept its original text", reasonText(d.error_class)]);
    return join(["Batch " + d.batch, num(d.cues) + " cues"]);
  },
  cues: (d) => join([num(d.cues) + " cues", "longest line " + d.max_line_chars + " of " + d.limit_line_chars + " characters", "up to " + d.max_lines + " lines"]),
  text: (d) => join([num(d.segments) + " segments", num(d.lines) + " lines", num(d.chars) + " characters"]),
  translate(d, status) {
    if (status === "running") return "Translating " + d.source + " to " + d.to;
    return join([d.source + " to " + d.to, num(d.cues) + " cues"]);
  },
  stored(d) {
    if (d.message && d.stored === false) return d.message;
    if (d.kind === "captions") return join(['Captions track "' + d.label + '"', num(d.cues) + " cues", d.speakers > 1 ? d.speakers + " speakers" : null, fmtBytes(d.bytes)]);
    return join(["Transcript saved (" + d.source + ")", d.engine ? d.engine + " (" + d.model + ")" : null, num(d.chars) + " characters", d.lang ? "language " + d.lang : null]);
  },
  retry(d) {
    const parts = [d.message];
    const why = reasonText(d.reason);
    parts.push(d.attempt ? why + ", attempt " + d.attempt + " of " + d.max_attempts : why);
    if (d.retry_after_s) parts.push("again in about " + fmtSecs(d.retry_after_s));
    return join(parts);
  },
  finished(d, status) {
    if (d.message) return d.message;
    if (status === "ok") return "Done in " + fmtSecs(d.seconds);
    return status;
  },
  failed: (d) => join([d.message, d.stage ? "while: " + stageLabel(d.stage).toLowerCase() : null]),
  delivered(d) {
    return d.client + " fetched " + (VIA_LABELS[d.via] || d.via) + (d.count > 1 ? " (" + d.count + " times)" : "");
  },
};

export function describe(event) {
  const fn = DESCRIBERS[event.stage];
  const detail = event.detail || {};
  try {
    return fn ? fn(detail, event.status) : "";
  } catch {
    return "";
  }
}

// Fold the raw log into display rows: a "running" event is replaced, in place, by the event of the
// same stage that ended it. Deliveries have their own section and are left out. `child` rows
// (per-chunk results and engine fallbacks) hang under the speech-to-text stage.
export function collapse(events) {
  const rows = [];
  const open = new Map();
  for (const ev of events) {
    if (ev.stage === "delivered") continue;
    const child = ev.stage === "asr_chunk" || ev.stage === "asr_fallback" || ev.stage === "proofread_batch";
    const row = { stage: ev.stage, status: ev.status, detail: ev.detail || {}, ts: ev.ts, end: ev.ts, child };
    const earlier = !child && ev.status !== "running" && open.get(ev.stage);
    if (earlier) {
      earlier.status = ev.status;
      earlier.detail = { ...earlier.detail, ...row.detail };
      earlier.end = ev.ts;
      open.delete(ev.stage);
      continue;
    }
    rows.push(row);
    if (ev.status === "running") open.set(ev.stage, row);
  }
  for (const row of rows) {
    const seconds = row.detail.seconds;
    row.seconds = seconds !== undefined && seconds !== null ? seconds : row.status === "running" ? null : row.end - row.ts || null;
  }
  return rows;
}

export function statusIcon(status) {
  return (
    { ok: "check", failed: "close", warn: "warn", skipped: "skip", running: "run", cancelled: "skip", interrupted: "warn", info: "info" }[status] || "info"
  );
}

export function statusKind(status) {
  return { ok: "ok", failed: "bad", warn: "warn", running: "run", interrupted: "warn" }[status] || "";
}
