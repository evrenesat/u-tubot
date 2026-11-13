# HQ captions

YouTube's automatic captions are often poor. u·tubot can build its own: when the video has captions, their timing is kept and the text is
improved; when it has none, the track is made from the audio. Both paths end in a WebVTT track the TV adds to the subtitle picker.
Speaker diarization is out of scope for now (owner, 2026-11-13); the pipeline only runs it when `[captions] diarization` is not `none`.

## Pipeline

1. **Queue.** *Video menu, Prepare HQ captions* (or `POST /v1/videos/ID/captions`) queues a persisted job. Jobs survive restarts and
   are processed `captions.job_concurrency` at a time (default 1). One job per video and language; repeated requests share it.
2. **Caption recheck.** The job asks once more what YouTube has for the video. When the answer is a caption track with timings and it
   matches the requested language, the job improves it ([below](#improving-existing-captions)); otherwise (no captions, a limited or
   unreachable caption endpoint, a track without timings) it builds the track from the audio. The check never holds the audio back.
3. **Download.** yt-dlp fetches the lowest-bitrate audio of the video's original-language track ([below](#which-audio-is-downloaded)) —
   from the media archive when it is already there — then `ffmpeg` converts it to 16 kHz mono WAV. Videos longer than `max_duration_s`
   (3 h) are refused. Every download is kept in the media archive, so no audio is ever fetched twice.
4. **Vocal separation** (optional): when `separation = "demucs"`, the vocals stem is separated from the music before ASR
   ([below](#vocal-separation)).
5. **ASR.** Speech recognition with word timestamps, chunked and stitched ([below](#asr-engines)). The answer is cached per video and
   audio, so a retried job or a second job for the same video does not transcribe the same audio twice.
6. **Cues and alignment.** Words are grouped into cues of at most `max_lines` (2) lines of `max_chars_per_line` (42) characters, 1 to 7
   seconds (`min_cue_s`, `max_cue_s`), breaking at sentence and speaker changes, and never faster than `max_cps` (20) characters per
   second. Cue boundaries are then nudged to nearby silences (`align_silence`), so a cue does not cut into a word.
7. **Proofreading.** The LLM (`[llm.captions]`) fixes punctuation, capitalisation, names and terms, using the video's title and
   description as context ([below](#proofreading)).
8. **Translation.** The job targets English by default (`[captions] translate_to`, "en"): a track in another language is translated
   ([below](#translation)), so the result is English captions whatever the source language. A track already in the target language is
   kept as it is.
9. **Store.** The track is saved as `<language> (u·tubot)`. Each stage is written to the
   job's event log with its time, and the web UI shows it as a timeline with the result and the clients that fetched it (`server.md`,
   Job details).

## Improving existing captions

When the video already has a caption track, its timing is the skeleton: each caption becomes a cue, rolling repeats of automatic
captions are dropped and text too long for one cue is re-broken (`max_lines` x `max_chars_per_line`, time shared by length). Then the
ASR words that fall inside each cue's window (plus `align_window_s`, 0.4 s) replace its text and move its boundaries to the words
actually spoken — the video's captions keep the timing, the speech recognition provides the better transcription. A cue the ASR heard
nothing in keeps the caption text. The proofreading pass runs last. When no speech engine is available, the caption text is proofread
and stored as it is.

## Proofreading

The cue texts go to the LLM in batches of `proofread_batch` (40) with the video's title and description (up to
`proofread_context_chars` each). The answer must be a JSON array with the same length and order as the batch; a different shape, an
empty string, or a batch whose text grew beyond `proofread_max_ratio` (1.6 — a sign of invention) falls back to the original texts. A
failing LLM never fails the job: those batches keep their text and the stage warns. Corrected batches are cached per video, so a
retried job does not pay twice.

## Translation

The goal is high-quality English captions for every requested video, whatever its source language (owner, 2026-11-13). The default
translation target is English: `[captions] translate_to` is `"en"`, the API leaves `translate_to` unset by default, and the TV app's
"prepare captions" request resolves to the same default. A track whose language differs is translated by the LLM (`translate_batch`, 40,
cues at a time) and — so the quality bar holds for the English output — the translated text is proofread again with the title and
description as context. Same-language captions stay available: pass `translate_to: "off"` (or "none") explicitly, or set
`[captions] translate_to` to `"off"` to make that the default.

## Vocal separation

With `separation = "demucs"` the pipeline runs `separation_cmd` (default `demucs --two-stems vocals`; install it with
`uv tool install demucs`) over the converted audio and feeds ASR the vocals stem. A speech-only mix loses almost nothing, so there is no
music detector. The stage is best-effort: a missing tool, a failure or `separation_timeout_s` (1 h) falls back to the original audio and
says so in the job log.
job while the video plays and, when it is ready, adds the track to the video and turns it on (you asked for it) with a short "u·tubot
captions ready"; at the start of a video the setting *Select HQ captions automatically* decides. The app fetches the VTT once, with
its `Authorization` header, and keeps the file in its own storage: the subtitle menu offers it for that video from then on, after a
restart or an update, with another backend or with this one off the air.

Every step above is written to the job's event log with its time, and the web UI shows it as a timeline with the result and the clients that
fetched it (`server.md`, Job details).

## ASR engines

Speech to text goes through a chain of engines. Each engine is one `[[captions.asr_engines]]` entry and is used when it is enabled
(its `api_key_env` variable is set, or it names none) and healthy. A video is sent to the best engine that serves its language; if that
engine fails, the work falls through to the next.

| Field | Default | Meaning |
|---|---|---|
| `name` | required | label in logs, `GET /v1/status` and the stored transcript (`engine`) |
| `kind` | `openai` | `openai`: any server with `POST /v1/audio/transcriptions` (OpenAI, mlx-audio/oMLX, whisper.cpp, vLLM, a CPU STT box). `faster_whisper`: local CPU (`uv sync --extra asr`) |
| `url` | required for `openai` | the full transcription URL |
| `model` | `whisper-1` / `small` | model name sent to the server; the faster-whisper size (`tiny` ... `large-v3`) for `faster_whisper` |
| `api_key_env` | none | name of the environment variable holding the key. Set: the engine is enabled only while the variable is non-empty. Omitted: no key is sent |
| `languages` | all | allow-list of language codes (`["en", "tr"]`). Known video language (from its metadata): engines whose list lacks it are dropped. Unknown language: engines without a list are preferred; if an allow-listed engine took a chunk anyway and the detected language is outside its list, the chunk is redone by the next engine that serves that language (its transcript is kept only when none does) |
| `max_chunk_s` | `600` | longest audio piece sent in one request (`0`: never cut). Respect the server's own limit; the last chunk may run up to 3 s over |
| `max_parallel` | `1` | requests in flight to this engine at once, shared by all jobs (a box that handles one job at a time gets `1`) |
| `timeout_s` | `900` | per request; connecting gives up after 10 s so a switched-off machine fails fast |
| `priority` | `100` | lower is tried first; equal numbers keep the order of the file |
| `background_only` | `false` | never used for jobs somebody is waiting on (summary view, explicit transcribe); only for passive work such as the side panel |
| `speed_factor`, `overhead_s` | `1.5`, `2.0` | audio seconds one stream transcribes per second, and fixed seconds per request; only used for the estimate shown to the user |
| `compute_type`, `threads` | `[captions] whisper_*` | `faster_whisper` only |

How an engine is chosen for a file: drop engines that are disabled, background-only (for interactive jobs) or whose `languages` do not
include the video's known language; put engines that failed in the last `asr_unhealthy_s` (300 s) after the healthy ones; sort by
`priority`; with an unknown language, engines without a `languages` list go before restricted ones. A failed request moves that chunk to the
next engine, which re-cuts it to its own `max_chunk_s` if that is smaller. Whether the engine is also marked unhealthy depends on what
failed: a connect or timeout failure, a 429 or a 401/403/404 mark it at once; a single 5xx, or an answer that is not a transcript, may be the
file's fault and only counts once a second, *different* file has failed on that engine within `asr_failure_window_s` (600 s) with no success in between; a request rejected for its
input (400, 413, 415, 422) never counts. A chunk that waited for an engine's `max_parallel` slot, or the next piece of a re-cut chunk, checks the engine
again: if it became unhealthy meanwhile and a healthy engine remains later in the chain, the work moves on at once instead of waiting
out another timeout. When every engine is unhealthy they are all tried again, so a single-engine setup recovers
by itself. The engines used and their models are stored with the transcript (`engine` is `mac+lan-cpu` when two shared the work).

**Example: three engines** (placeholders; use your own hosts and variable names):

```toml
[[captions.asr_engines]]            # a Mac Studio running oMLX (mlx-audio): everything, three 10 minute chunks at once
name = "mac"
kind = "openai"
url = "http://mac.example:8901/v1/audio/transcriptions"
model = "whisper-large-v3-turbo-asr-fp16"
api_key_env = "UTUBOT_ASR_API_KEY"
max_chunk_s = 600
max_parallel = 3
timeout_s = 300
priority = 10
speed_factor = 35.0                 # measured: about 37 audio seconds per second per stream

[[captions.asr_engines]]            # a small CPU speech-to-text box: English and Turkish only, one chunk at a time, background work only
name = "lan-cpu"
kind = "openai"
url = "http://stt.example:8788/v1/audio/transcriptions"
model = "stt"
api_key_env = "UTUBOT_LAN_STT_KEY"
languages = ["en", "tr"]
max_chunk_s = 540
max_parallel = 1
timeout_s = 900
background_only = true
priority = 20
speed_factor = 4.0

[[captions.asr_engines]]            # always available: faster-whisper on this machine
name = "local"
kind = "faster_whisper"
model = "small"
max_chunk_s = 600
priority = 30
speed_factor = 1.5
```

With this chain a summary somebody opens uses the Mac; when the Mac is off (connection refused within 10 s) it falls to the local model
and the Mac is skipped for five minutes. An English side-panel transcription can go to the CPU box while the Mac is busy elsewhere.
Japanese audio never reaches the CPU box (`languages`). The Mac and local engines are not restricted, so they take any language.

**Single backend (old keys).** Without any `asr_engines`, `asr_backend`, `asr_url`, `asr_api_key_env`, `asr_model`, `asr_chunk_s`,
`asr_timeout_s`, `whisper_*`, `asr_speed_factor` and `asr_overhead_s` describe one engine called `default` (one request at a time,
the key optional). Nothing in an existing config needs to change. Entries in `asr_engines` replace these keys.

### Chunking and stitching

Audio longer than the engine's `max_chunk_s` is cut into chunks that overlap by `asr_chunk_overlap_s` (2 s), so a word on a cut is whole
in one of the two. Chunks run in parallel up to `max_parallel`. When they are stitched back, each chunk keeps only what lies on its side
of the middle of every overlap, and text that both sides still said (at least two words repeated at the seam) is dropped once.
Timestamps are offset to the full audio. A progress report is `finished chunks / total chunks` of the ASR step; the whole job is
about 2 % download start, 20 % downloaded, 25 % converted, then the ASR step up to 85 %.

A transcript made this way is stored with its segments (start, end, text), the language Whisper detected most (by audio seconds), the
engine and the model, and shown to clients as `source: "asr"` (`GET /v1/videos/ID/transcript` adds `engine` and `model`).

### Measured speed

One setup (the Mac engine above, three chunks in parallel): a 29.5 minute lecture took 2.5 s to download (10.7 MB of Opus), 3.4 s to
convert and 16.4 s for ASR (about 108 times real time); the whole job, YouTube pacing included, took about 31 s. A 5.6 minute video took
4 s to download and 4.7 s for ASR (one chunk, about 72 times real time). Your numbers depend on your engine: put them into
`speed_factor` and `max_parallel` so the estimates are right.

### Estimates

The `estimate_s` shown with `needs_transcript` and while a job runs is `download_overhead_s + duration / download_speed_factor` (the
audio download, 5 s plus 300 audio seconds per second by default) plus the chosen engine's `overhead_s + duration /
(speed_factor x parallel)`, where `parallel` is the engine's `max_parallel` capped at the number of chunks. "The chosen engine" is the
one the selection above would pick right now for that video's language and priority.

### CPU performance

Local `small` with `int8` on a modern CPU with 4 threads transcribes a short clip several times faster than real time after the first
model load (a 19 second clip took about 7 seconds in testing, including load). Expect roughly real time or better for `small` and
a few times slower than real time for `medium`/`large-v3` on a desktop CPU; a 1 hour video can take from 10 minutes to over an
hour depending on model and cores. Keep `job_concurrency = 1` and `whisper_threads` at your physical core count, and use a remote
engine or a GPU server first in the chain for long videos.

## Which audio is downloaded

A video may carry several audio tracks: the original, YouTube's AI-dubbed translations, an audio description. "Worst audio" can land on a
dub, and the transcript is then in the wrong language. The downloader therefore picks from yt-dlp's format list itself
(`captions/formats.py`), the lowest bitrate of the **original-language track**:

1. audio-only formats whose track is marked `original` (`format_note`), lowest bitrate;
2. else audio-only formats that are not dubbed or described and belong to the preferred track (higher `language_preference`, or the one
   marked `(default)`) when the tracks differ;
3. else audio-only formats that are not dubbed or described (single-track videos);
4. else audio-only formats of any track (only when every track is a dub, so no original is offered);
5. else the same steps over formats that carry video too (the smallest muxed stream; `ffmpeg` drops the video);
6. else yt-dlp's own selector, `captions.audio_format` (`bestaudio/best`).

Plain HTTPS streams beat manifests, and loudness-compressed (DRC) copies lose ties. Real multi-track videos mark only the original
(`English (US) original (default)`); the other languages are named by language alone, so the rule is "the marked original, never another
track".

## YouTube's JavaScript challenge

yt-dlp needs a JavaScript runtime (deno by default) and a solver script to unscramble some stream URLs; without them it warns about the
"n challenge" and some formats are missing. A service started by systemd often has no `deno` on its `PATH`, so tell the backend:

```toml
[youtube]
js_runtime = "deno"                      # deno, node, bun or quickjs
js_runtime_path = "/usr/local/bin/deno"  # the executable (example path)
remote_components = ["ejs:github"]       # lets yt-dlp fetch its solver script once; it is cached
```

`js_runtime` is always passed to yt-dlp: without `js_runtime_path` yt-dlp looks the runtime up on `PATH` (so `js_runtime = "node"` works
alone). `remote_components` needs yt-dlp 2025.11.12 or newer, which is the floor in `pyproject.toml`.

On a host with only `js_runtime_path`, yt-dlp still logs `n challenge solving failed`: the solver script (`yt-dlp-ejs`) must come from
`remote_components` or be installed as the matching package (`yt-dlp[default]`). Both the metadata fetch and the audio download get
these options.

## Diarization (speaker labels)

Out of scope for now (owner, 2026-11-13): captions are produced without speaker labels unless this is configured. Off by default
(`diarization = "none"`); the pipeline only runs the stage when it is set to something else. It uses pyannote.audio and the gated
Hugging Face model `pyannote/speaker-diarization-community-1`.

1. `uv sync --extra diarization` (pulls PyTorch; several GB).
2. Create a Hugging Face account, open the model page of `pyannote/speaker-diarization-community-1` and accept its conditions.
3. Create a *read* access token in your Hugging Face settings.
4. Put it in the environment of the service as `UTUBOT_HF_TOKEN` (the variable named by `captions.hf_token_env`), for example in
   `/etc/utubot/env`. Never in `config.toml`.
5. Set `diarization = "pyannote"` and restart.

If the token or the package is missing, diarization is skipped with a log warning and captions are produced without speakers. It runs on
CPU and adds substantial time on top of ASR (often similar to the audio length); it is most useful for interviews and podcasts.

## Transcripts for videos without captions

The same pieces build a plain-text transcript for videos YouTube has no captions for (the "fast path": no diarization, no VTT, segments
only). The backend never summarises such a video from its title. What happens instead depends on the user's policy:

- **Automatic** (`auto_transcribe`, [policy.md](policy.md)): the request that found no captions queues the transcription itself and
  answers `status: "pending"`, `transcript_status: "transcribing"` with `progress` and `estimate_s`; asking again reports the progress
  until the transcript exists and the summary, insight or answer is made as usual. `on_open` (the default) starts it when the user opens
  the video (Summary view, insight, answer, an ad-hoc summary); `on_dwell` also starts it from the side panel (`prompt=panel`), which
  only lingers on a video. Only videos up to `auto_transcribe_max_minutes` (30) qualify, and their length must be known. `off`, longer
  videos, a full per-user queue (`transcribe_max_active_per_user`) and videos no engine can take still answer `needs_transcript`
  with `can_transcribe` and the TV asks "Transcribe in background?".
- **Priority.** A transcription somebody is waiting on (opened video, `POST /v1/videos/ID/transcribe`) is an *interactive* job: it is
  claimed before background jobs, uses the gate and the engines at interactive priority, and may use any engine. A side-panel job is a
  background job; when the user then opens the video, it is promoted. Background-only engines never take interactive jobs.
- **Explicit.** `POST /v1/videos/ID/transcribe` queues a job regardless of the policy (one per user and video; asking again returns
  the same job).
- **YouTube limits the caption API.** When the caption class is cooling (or its probe is out, see
  [server.md](server.md#youtube-limits-and-the-transcription-fallback)), or a caption fetch has just been refused (429, 403), and the
  `media` class is healthy and an engine can take the video, the request is treated like "no captions": the policy above decides between
  starting the job (`pending` + `transcribing`) and `needs_transcript` with the message "Captions are temporarily unavailable from YouTube;
  transcribe the audio instead (~N s)?". The answer is `delayed` only when no engine is available, the video cannot be transcribed (live,
  too long), or the media class is cooling as well (a bot check blocks both). The result is stored with source `asr`; captions fetched
  later never replace it, and ASR never replaces captions stored first (the first transcript stays, no refetch).

A job downloads the audio through the YouTube gate ([server.md](server.md#youtube-limits-and-the-transcription-fallback)), runs the ffmpeg
and chunked ASR steps above (language from the video's metadata when known, else detected) and stores the text, its segments, the
engine and the model as the video's transcript with source `asr`. Summaries, insights and answers then work as usual and say
`source: "asr"`. Progress is in `GET /v1/videos/ID/transcript` and in `GET /v1/jobs` (done chunks over all chunks during the ASR step);
the estimate is described [above](#estimates). `transcribe_max_active_per_user` (5) limits queued jobs per user. Queued jobs are claimed
interactive first, then oldest first (`job_concurrency` runs that many at a time).

Jobs wait while the **media** endpoint class is cooling; a limit on the caption or metadata endpoints does not hold them back (the check
for captions that appeared since is then skipped and the audio is transcribed). An interactive job also skips that check while the caption
class waits for its probe. A job whose download is refused (429, network) goes back to the queue,
at most `job_max_attempts` (3) times, then fails; a problem of the one video (private, members-only, 403/410 on its media, live, longer than
`max_duration_s`) fails it at once without touching the YouTube breakers. Before downloading, the job asks YouTube once more for
captions when those endpoints are healthy: if they exist they are used and the audio is skipped, and a transcript from the audio never
replaces YouTube captions. Live streams and videos over `max_duration_s` are refused from yt-dlp's real info before any download, and
audio over `max_download_bytes` is skipped. Audio downloads hold the YouTube gate only until they start, so they do not delay interactive
fetches. Scratch directories a crash left under `data_dir/media` are swept at start.

## Checking on jobs

The web UI has a *HQ captions and background jobs* section (queue a video, status; all your jobs, including transcriptions). `GET /v1/jobs`
lists your jobs of every kind (`kind` `captions` or `transcript`, `state` `waiting|processing|ready|failed`); `GET /v1/captions/jobs` lists your recent caption jobs;
`GET /v1/videos/ID/captions` gives the status and tracks. Failures are logged by the service (`journalctl -u utubot`); the API only
returns generic messages.

## If YouTube blocks the server

Datacenter addresses are sometimes refused. Export cookies from a logged-in browser in Netscape format and set
`transcripts.cookies_file`. Keep that file private (it is a credential).
