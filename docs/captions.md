# HQ captions

YouTube's automatic captions are often poor. u·tubot can build its own: the backend downloads the audio, transcribes it with
Whisper, optionally labels speakers, and serves a WebVTT track the TV adds to the subtitle picker.

## Pipeline

1. **Queue.** *Video menu, Prepare HQ captions* (or `POST /v1/videos/ID/captions`) queues a persisted job. Jobs survive restarts and
   are processed `captions.job_concurrency` at a time (default 1). One job per video and language; repeated requests share it.
2. **Download.** yt-dlp fetches the best audio (`audio_format`), then `ffmpeg` converts it to 16 kHz mono WAV. Videos longer than
   `max_duration_s` (3 h) are refused.
3. **ASR.** Speech recognition with word timestamps (below).
4. **Diarization** (optional): speaker turns are matched to words.
5. **Cues.** Words are grouped into cues of at most `max_lines` (2) lines of `max_chars_per_line` (42) characters, 1 to 7 seconds
   (`min_cue_s`, `max_cue_s`), breaking at sentence and speaker changes.
6. **Store.** The track is saved as `<language> (u·tubot)` or `<language> (u·tubot, N speakers)`. Speaker turns are prefixed
   `[S1] `, `[S2] `. The downloaded media is deleted unless `keep_media = true`.

Optionally `translate_to` translates the cues with `[llm.captions]`. Captions are shared by everyone on the server. The TV polls the
job and, when ready, adds the track; with *Select HQ captions automatically* it is turned on for you. The app fetches the VTT with
its `Authorization` header.

## ASR backends

Choose with `captions.asr_backend`. The example config uses `faster_whisper`; the built-in default is `openai`.

| Backend | Where | Setup |
|---|---|---|
| `faster_whisper` | local, CPU (int8) | `uv sync --extra asr`; `whisper_model` (`tiny`, `base`, `small`, `medium`, `large-v3`), `whisper_compute_type`, `whisper_threads`. Models download from Hugging Face on first use into the cache. |
| `openai` | any server with `POST /v1/audio/transcriptions` | `asr_url`, `asr_model` (`whisper-1`), key in the variable named by `asr_api_key_env` (default `UTUBOT_ASR_API_KEY`). Long audio is cut into `asr_chunk_s` (600 s) chunks. Works with OpenAI and local servers that offer the endpoint. |

### CPU performance

Local `small` with `int8` on a modern CPU with 4 threads transcribes a short clip several times faster than real time after the first
model load (a 19 second clip took about 7 seconds in testing, including load). Expect roughly real time or better for `small` and
a few times slower than real time for `medium`/`large-v3` on a desktop CPU; a 1 hour video can take from 10 minutes to over an
hour depending on model and cores. Keep `job_concurrency = 1` and `whisper_threads` at your physical core count. Use a remote
`openai` backend or a GPU server for long videos.

## Diarization (speaker labels)

Off by default (`diarization = "none"`). It uses pyannote.audio and the gated Hugging Face model
`pyannote/speaker-diarization-community-1`.

1. `uv sync --extra diarization` (pulls PyTorch; several GB).
2. Create a Hugging Face account, open the model page of `pyannote/speaker-diarization-community-1` and accept its conditions.
3. Create a *read* access token in your Hugging Face settings.
4. Put it in the environment of the service as `UTUBOT_HF_TOKEN` (the variable named by `captions.hf_token_env`), for example in
   `/etc/utubot/env`. Never in `config.toml`.
5. Set `diarization = "pyannote"` and restart.

If the token or the package is missing, diarization is skipped with a log warning and captions are produced without speakers. It runs on
CPU and adds substantial time on top of ASR (often similar to the audio length); it is most useful for interviews and podcasts.

## Transcripts for videos without captions

The same pieces build a plain-text transcript for videos YouTube has no captions for. The backend never summarises such a video from
its title; it answers `needs_transcript` and the TV asks "Transcribe in background?". `POST /v1/videos/ID/transcribe` queues a job
(one per user and video; asking again returns the same job) that downloads the audio through the YouTube gate
([server.md](server.md#youtube-limits-and-the-transcription-fallback)), runs the ffmpeg and ASR steps above (language auto-detected,
no diarization, no VTT) and stores the text as the video's transcript with source `asr`. Summaries, insights and answers then work as
usual and say `source: "asr"`. Progress is in `GET /v1/videos/ID/transcript` and in `GET /v1/jobs`; the estimate shown beforehand is
`asr_overhead_s` plus the video length divided by `asr_speed_factor` (set it to what your ASR backend really does). `transcribe_max_active_per_user`
(5) limits queued jobs per user. Queued jobs wait while YouTube has the server in a cooldown and a job whose download is refused goes
back to the queue instead of failing.

## Checking on jobs

The web UI has a *HQ captions and background jobs* section (queue a video, status; all your jobs, including transcriptions). `GET /v1/jobs`
lists your jobs of every kind (`kind` `captions` or `transcript`, `state` `waiting|processing|ready|failed`); `GET /v1/captions/jobs` lists your recent caption jobs;
`GET /v1/videos/ID/captions` gives the status and tracks. Failures are logged by the service (`journalctl -u utubot`); the API only
returns generic messages.

## If YouTube blocks the server

Datacenter addresses are sometimes refused. Export cookies from a logged-in browser in Netscape format and set
`transcripts.cookies_file`. Keep that file private (it is a credential).
