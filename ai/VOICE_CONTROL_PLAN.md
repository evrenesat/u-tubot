# Voice control: talk to the TV, and a phone app with a robot mode (plan, epic #189)

Status: draft, revision 1. Waits for the owner's decisions (Part 1). Nothing is implemented and no service is changed.
Scope: the owner speaks, from a phone or to the TV itself, and the TV does it for the content in focus: describe a cut,
play it, next part, HQ subtitles, a summary, research, play, pause, seek, or a question about what is on screen. Three
pieces are added: a **live server** (Go, grown from R2T4's server) that carries audio, the TV control channel and the
push to every device; a **command model** (a fixed tool list over actions u·tubot already has); and a **native phone
app** built from R2T4's Android app, with a classic mode and a hands-free robot mode. The existing Python backend keeps
every feature it has and gains only small additive routes. The menus, the remote and the phone cut sheet stay as they are.
Related: #189 (epic), #180 to #188 (its pieces), #176 (voice custom cut on the TV, in work), #177 (voice comments,
backlog), #158 (answers scroll by themselves), #160 (Inbox), #161 (research), `ai/CONTRACT.md`,
`ai/BROWSER_EXTENSION_PLAN.md` (parity rule), `ai/CUT_MODES_PLAN.md` and `ai/RESEARCH_MODE_PLAN.md` (the plan format and
the request, long-poll and announcement patterns reused here), and the owner's public repository `evrenesat/r2t4`.

---

# Part 1: owner plan

## What changes for you

- **First usable step (checkpoint 4):** open u·tubot's page on your phone, hold **Talk**, say "make a cut that keeps only
  the benchmarks". The TV shows what it heard, starts the cut for the video it has in focus, and applies it when it is
  ready, as it does today for a cut described on the phone. "Pause", "back thirty seconds", "next part" and "cut off"
  work the same way and act in about a second.
- **The phone app (checkpoint 6):** one app called u·tubot. *Classic* is what the phone page does today (cut sheet, jobs,
  share from YouTube) plus a big Talk button and a line that says what the TV is showing. *Robot mode* is R2T4: the phone
  sits near the TV, listens for a wake word or a tap, answers by voice, and needs no hands. You switch between them in
  the app; neither replaces the other.
- **Talking to the TV itself (checkpoint 9):** a mic button in the player and in the u·tubot menu. It only appears on a
  TV whose microphone gives usable sound (the probe of #176 decides). The TV pauses while it listens, unless you are on
  headphones.
- **Answers (checkpoints 7 and 8):** a short text card on the TV, and speech on the phone or headphones if you want it.
  Long answers open the normal text view ("show more"), which scrolls by itself once #158 has landed. "What did he just
  say?" and "explain this part" answer from the transcript around the current position and name the time.
- **Nothing happens behind your back:** each device is off until you switch voice on for it; a mic symbol is on the TV
  whenever any microphone of yours is live; sound is never stored; one switch turns it all off.
- The extension gets the same as a late step: a Talk button in its panel and voice commands for the tab that plays
  (checkpoint 12, after a feasibility check).

## How fast it should feel

**Targets, not measurements.** Checkpoint 0 measures the engines, checkpoint 5 measures the whole path on your devices
and corrects this table. Times count from the moment you stop speaking.

| Step | Simple command ("pause", "next part") | Open command ("make a cut that …") |
|---|---|---|
| Last sound reaches the live server | 0.1 s | 0.1 s |
| Speech to text (our own engine) | 0.4 s | 0.6 s |
| Deciding what you meant | almost 0 (fixed phrases, no model) | 0.6 s (small local model) |
| TV receives it and acts | 0.2 s | 0.2 s |
| **You see it happen** | **about 0.7 s, at most 1.5 s** | **about 1.5 s, at most 2.5 s** |
| Spoken reply starts (if on) | 0.5 s later | 0.5 s later |

The TV shows "Listening…" the moment you press Talk and the words it heard as soon as they exist, so you are never
waiting on a blank screen. The cut itself, a summary or research take as long as they take today; voice only starts them.

## Decisions needed from you

Decision 2 blocks checkpoint 2 and checkpoint 6. Decision 3 shapes everything and is taken as you stated it on
26 November. The others can be taken as recommended and changed later.

1. **One phone app with two modes, in this repository** (recommended). R2T4's Android app is copied into `phone/`,
   renamed to u·tubot (`dev.utubot.phone`), and gets pairing, the Talk button and the classic screens; its capture
   service becomes robot mode. Inside it the audio, connection and settings code is a small library module so it can be
   tested without a phone. Alternative: two separate apps (u·tubot and R2T4) sharing that library: twice the releases,
   signing and pairing for one user.
2. **Blocking: copy R2T4's `android/` and `server/` into u·tubot under MIT** (recommended; the reply needed is "yes,
   MIT"). `evrenesat/r2t4` is public and has no licence file. You gave the same yes for `scene-analyser` in the cut modes
   plan; this covers the other two directories. The R2T4 repository stays as the archive of the experiment.
3. **The live server is Go and is the real-time layer; Python stays behind it for the features** (your choice, adopted).
   Audio in and out, the TV channel and the push to TVs and phones live in the Go server grown from R2T4's. Cuts,
   captions, summaries, research, accounts and settings stay in the Python backend, unchanged. What the numbers say,
   honestly: about nine tenths of the wait is the speech and language models, and Go does not shorten those. Go keeps the
   remaining hops at a few milliseconds, keeps every device connected while the Python backend restarts on a deploy, and
   keeps audio off the one loop that also serves caption and cut work. Alternative: put the channel into the Python
   backend (one service fewer; the live path then shares that loop and drops on every backend deploy).
4. **First step uses the phone page you already have, the native app comes right after** (recommended). You can talk to
   the TV after five checkpoints instead of seven. Alternative: wait for the native app.
5. **Push-to-talk first; a wake word only with an open engine, and no Picovoice in the public app** (recommended).
   Picovoice needs a personal access key in every install, reports usage to its servers, and its terms forbid passing the
   licence on; the free plan's limits could not be read from here (section 5.2). Checkpoint 10 tests an open keyword
   engine against a fixed bar with the TV playing; if it fails, robot mode stays tap-to-talk. Alternative: a private
   build flavour with your own Picovoice key and R2T4's existing "R2T4" wake word (works today if your key is still
   valid, cannot be given to anyone else).
6. **Models: no model for the player commands, `fast` for understanding, `coder` for questions, no cloud for voice**
   (recommended, settled by the measurement of checkpoint 5). Alternative: allow the cloud alias as fallback for
   questions only, inside the $1 a day; the question and the transcript excerpt then leave the house, your voice never.
7. **Ask before anything costly, do everything else at once** (recommended). The TV asks "Start a watched cut, about
   N min? OK / Back" (or you say yes or no) for: a watched cut, research, transcribing or HQ subtitles from audio for a
   video over 30 minutes, and anything that would use the cloud. A quick cut, a summary, play, seek and the like start
   immediately.
8. **Privacy defaults** (recommended): voice off per device until you switch it on; sound is never written to disk; the
   text of each command is kept 30 days so you can see what was heard (setting: 0, 7, 30 days); R2T4's continuous
   recording and its photo every 2 seconds are **not** carried over. Later, a question like "who is this?" may take one
   photo at that moment, if you allow the camera. Alternative: keep continuous capture as an opt-in of robot mode.
9. **Phone app releases like the TV app** (recommended): a signed APK on the repository's releases, mirrored by your
   server, with the same in-app update check; signed with the TV app's key. This is a public release, so the first one
   waits for your explicit go. Alternatives: Obtainium pointing at the releases (no code), or the Play Store (a $25
   account, review, and Google's rules for always-on microphones).
10. **On the TV: a mic button on screen, the TV pauses while it listens** (recommended). The remote's own mic key
    belongs to the Google assistant on most TVs and is not relied on. While listening: TV microphone → pause; phone
    microphone → lower the volume; headphones → leave it. Alternative: a remote key held down (which key is decided on
    your TCL after the probe).
11. **English commands first** (recommended). Another language is a second evaluation set and no code. Alternative: name
    the second language now and it is measured in checkpoint 5 too.
12. **Spoken replies: off on the TV's speakers, on in robot mode and on headphones; text always** (recommended).

## What I need from you

| What | When | Recommendation |
|---|---|---|
| Decisions above | before checkpoint 1 | take the recommended ones; 2 needs the words "yes, MIT" |
| The live server deployed next to the backend, and the proxy passing `/rt/` with WebSocket upgrade | checkpoint 2 lands | an infra task in the operations repository; same machine as the backend, second service |
| Model gateway: a speech-to-text alias and a text-to-speech alias usable by u·tubot, and the `fast` and `coder` aliases | checkpoint 0 | the names go in the config, nothing is hard-coded |
| Ten minutes at the TV: 40 short spoken commands recorded with the Talk page, half with the TV playing | checkpoint 5 | this is the evaluation set for sound; the sentences are provided |
| Your TCL TV for the microphone probe | #176, then checkpoint 9 | already asked in #176 |
| A phone for the app; an old phone for robot mode | checkpoints 6 and 10 | the Moto Z Play R2T4 ran on is fine for robot mode |
| Go for the first public phone release | checkpoint 6 | see decision 9 |
| No new account is needed | | no Picovoice, no Play Store, no cloud speech |

## How long

From the finished flows of this project: half took under 6.7 hours from start to merge, four of five under 26 hours.
This plan is 13 pull requests after the gate. The first usable step is 4 of them: about a day and a half of agent time
at the usual pace, three if one runs long. Everything: about 90 hours at the usual pace, about 150 with the long ones
that history predicts, so two to three calendar weeks with your tests in between and one Android build running at a
time. Go and a new Android project are new to this repository, so the first live-server and phone checkpoints are more
likely to be the long ones. These are projections from history, not promises.

## Risks

- The small local model may misread open commands. Checkpoint 5 measures it on a fixed list before you depend on it; the
  player commands do not use a model at all, and nothing costly starts without your OK.
- Speech recognition with the TV playing may be poor on the phone and worse on the TV's own microphone. You said you
  mostly speak when it is muted or on headphones; the plan pauses or lowers the TV while listening and does not try to
  cancel echo.
- The TV's microphone may not be usable by an app at all on your TCL. Then the TV has no mic button and the phone is the
  microphone; nothing else changes.
- A wake word next to a talking TV triggers by mistake. The bar in checkpoint 10 is strict; failing it means tap-to-talk.
- One more service to run. If the live server is down, everything that exists today works exactly as today.
- The speech and `fast` engines are shared with other u·tubot work. A busy engine makes voice slow; the answer is "busy,
  try again", never a long silent wait.

---

# Part 2: agent plan

## 1. Facts checked

### 1.1 u·tubot (repository state at `d15a21d6`)

- Auth and pairing: `ai-backend/src/utubot/auth.py`. One bearer token per device (`device_tokens`: id, user, hashed
  token, device name, last used); `POST /v1/pair` redeems a 6-digit code; `POST /v1/me/pair` makes one for the caller;
  browsers use a cookie session (`webauth.py`, CSRF header on writes, `POST /v1/auth/login {"token"}` accepted).
  `/setup.json` carries `backend_url`, `update_url`, `pairing`, `defaults`, `prompt_set_urls`.
- Speech already exists as dictation: `speech.py`, `POST /v1/speech` (multipart audio in, `{"text"}` out, 4 MiB,
  10 per minute per user, nothing stored), forwarding to the model gateway's `/v1/audio/transcriptions` under
  `[speech] alias`. The gateway's engine refuses a recording over about 55 s. The phone page's Speak button
  (`web/ui/js/pages/cuts.js`) records with `MediaRecorder` (webm or m4a); `Permissions-Policy` allows `microphone=(self)`.
- Nothing pushes: the backend has no WebSocket, no server-sent events. Clients long-poll (`GET /v1/cuts/{id}?wait_ms=`,
  cap 20 s; the TV's `UtubotCutFollower` uses 10 s). The backend is one FastAPI process (`fastapi`, `uvicorn`, `httpx`);
  cut and caption work run as tasks on the same event loop.
- Jobs and events: `jobs`, `job_events` (`captions/events.py`), `cut_requests` with stages and progress; a ready cut is
  announced on the TV with a one-press Apply (`UtubotCutController.onCutReady`).
- Model client: `llm.py`, string message content, `chat_json` with one repair retry, priorities `INTERACTIVE` and
  `BACKGROUND`, a `fallback` chain per task; no tool-calling API. `POST /v1/videos/{id}/ask` answers a question from
  the whole transcript and takes no position.
- TV app: AI code in `common/.../utubot` (46 classes) and `tv/utubot`. `UtubotClient` is blocking OkHttp with its own
  client; `UtubotMenu` holds the actions (answer, summary, prepare captions, force captions, cuts, describe on phone);
  `UtubotUiHost` knows whether the player is the screen; `FocusDebouncer` and `PanelCoordinator` know the focused card;
  `UtubotKeys` maps Info to the Summary view. The manifest already declares `RECORD_AUDIO`; the only speech code is the
  platform `SpeechRecognizer` in the inherited search and keyword filter. No raw microphone capture exists yet (#176
  adds it with a probe screen first).
- Extension: Manifest V3, network only in the background, background written for a service worker with "no timer that
  must outlive one request" (`extension/AGENTS.md`). Checkpoints 0 to 5 have landed; the panel and cuts are later ones.
- In flight and relevant: #176 (TV speech input and the reusable capture component), #158 auto-scroll (PR #168), #160
  Inbox (PR #171), research (plan merged, checkpoint 1 is #170).
- CI: `.github/workflows/utubot-ci.yml` has path-filtered jobs `backend`, `app`, `extension` on hosted runners (the
  repository is public); no Go job. `utubot-release.yml` signs and publishes the TV APK; the backend's app channel
  (`appchannel.py`, `GET /app/update.json`) serves one app.

### 1.2 R2T4 (`evrenesat/r2t4` at `29075554`, last commit March 2026; public, no licence file)

| Part | What it is | Use here |
|---|---|---|
| `android/` (Kotlin, 3,115 lines, Compose, minSdk 26, target 35, app id `com.r2t4.app`) | `CaptureService` (foreground service, camera and microphone types), `AudioRecorder` (16 kHz mono, 5 s WAV chunks plus a frame stream, optional `UNPROCESSED` source), `PromptRecorder` (energy threshold, stops after 1.5 s of silence or 15 s), `WakeWordDetector` (Porcupine 4.0.0, custom `r_two_t_four.ppn`, needs an access key), `ImageCapturer` (CameraX, a photo every 2 s), `UploadManager` (queues, retry, backlog guard), `R2T4Client` (hand-written JSON calls), settings and two Compose screens | Copied and adapted (2.9). Reused as is: recorder, prompt recorder, service shell, settings pattern. Replaced: client, upload manager's targets, wake word behind an interface. Dormant: image capturer, ambient chunks |
| `server/` (Go 1.24, 2,239 lines without generated code, Connect-RPC) | `UploadService` (unary audio chunk and image), `PromptService` (client-streamed prompt, a queue whose processor writes a placeholder answer), `AdminService`, `PluginService` (spawned plugins), file storage per device, an embedded admin page | Skeleton copied (2.2): `main`, config, graceful shutdown, the admin page shell. Not carried: file storage of ambient data, plugins, the proto surface |
| `proto/` | Connect-RPC definitions; the Android client does not use the generated code | Not carried (2.3) |
| `scene-analyser/` | Already adapted into `ai-backend/src/utubot/watch/` | No change |

Known gaps stated by R2T4's own documents: no authentication, cleartext allowed, no tests in either part, the prompt
path answers a placeholder (no speech-to-text, no model). Its recorded result: 8 hours of continuous capture on a
Moto Z Play with under 1 % chunk loss on the LAN.

So the honest inventory is: the phone side of capture is real and proven; the server's hot path for this epic (stream
audio in, decide, push to a TV) does not exist in either code base and is new code whichever language holds it.

### 1.3 Wake word licences (read 26 November 2026)

- Picovoice Terms of Use (effective 30 March 2026): the licence is "non-transferable, non-sublicensable"; usage data is
  held on the device and "pushed to a Picovoice server" when online; every user "needs to have a valid AccessKey". The
  pricing page returned nothing, so the free plan's limits, whether custom keyword files expire, and the cheapest paid
  plan are not known here.
- openWakeWord: code Apache-2.0, its pre-trained models CC BY-NC-SA 4.0 (not fit for an MIT repository's releases).
- sherpa-onnx: Apache-2.0, lists keyword spotting and Android; the licences of its keyword models were not read.

## 2. Decisions (all made, owner decisions of Part 1 assumed as recommended)

### 2.1 Shape

```
phone app / phone page / extension          TV app / extension tab
   (controller: microphone, speaker)           (screen: focus, executes)
            \                                   /
             \__ WebSocket /rt/v1/ws __________/
                         |
                  live server (Go)  ---- model gateway: speech-to-text, intent model, text-to-speech
                         |
                  backend (Python)  ---- token check, voice settings, command history, questions
                                         (TVs and phones keep calling it directly for every existing feature)
```

A command never passes through Python on its way to the TV. The TV carries out a command by calling the same code its
menu calls, which talks to the Python backend exactly as today.

### 2.2 Go or Python, per component

| Component | Lives in | Why |
|---|---|---|
| Device connections, heartbeats, push to TVs and phones | Go | Long-lived sockets must survive backend deploys (the backend restarts on every merge that touches it) and must not wait behind caption or cut work on the backend's single event loop |
| Audio in (frames from a microphone), audio out (speech to a speaker) | Go | Binary frames are relayed while the user still speaks, so nothing is left to upload at the end; one goroutine per stream, no shared loop |
| Focus store, target choice, command routing, acknowledgements, timeouts | Go | In-memory state next to the sockets; a round trip to another service per command would add a hop to every budget |
| Fixed-phrase matcher and the intent call (tool choice) | Go | On the live path between text and push; the model is reached through the gateway directly |
| Calls to speech-to-text and text-to-speech | Go | Same reason; the gateway is the only engine address either service knows |
| Who the token belongs to, per-device voice consent, retention settings | Python | One user store, one settings store, one Devices page; the live server asks and caches (2.4) |
| Command history | Python | One database; written after the fact, never on the live path |
| Cuts, captions, summaries, research, prompts, jobs, the web UI | Python | Unchanged |
| Questions about the video (`ask` with a position) | Python | Needs the transcript, the cut and the summary, which live there |
| Dictation into a text box (`POST /v1/speech`, #176, #177) | Python | Exists; not a live command: the user reads and edits the text first |

What Go buys in numbers, stated plainly: of the 1.5 s target for an open command, speech-to-text and the intent model
are about 1.2 s (2.5). Those are engine times and are the same from either language. The live server's own share is
budgeted at 5 ms per hop and 20 ms in total, checked in CI (2.5). The same hops inside the Python backend would
usually cost a few milliseconds more, which nobody would notice; what would be noticed is the tail: a blocked event
loop adds its full stall to every hop, and a deploy drops every socket. Checkpoint 0 measures the backend's loop lag
on the owner's server (99th percentile over a day of normal use) so this argument has a number; if it is under 20 ms
and the owner prefers one service, the fallback is recorded in 2.14, not built.

Layout: a new Go module in `realtime/` (binary `utubot-rt`), its own `AGENTS.md`, `README.md` and `DEVLOG.md`. R2T4's
`server/cmd`, `internal/config` and `internal/web` are copied with an origin header and listed in
`realtime/THIRD_PARTY.md`. Dependencies: the standard library plus one WebSocket package under a permissive licence
(`github.com/coder/websocket`, ISC). No cgo, no audio decoding in the server, no database: the live server keeps no
file. Configuration is a TOML file and environment variables for keys, like the backend's.

### 2.3 The control channel

One WebSocket per device: `GET /rt/v1/ws` on the live server, reached under the backend's own host through the reverse
proxy (`realtime_url` in `/setup.json` and in `GET /v1/me` names it; absent means no voice). JSON text frames for
control, binary frames for audio. Connect-RPC and the proto files are not carried over: browsers cannot stream both
ways over it, the TV app is Java on a forced old OkHttp line, and R2T4's own client never used the generated code.
The house style of a JSON contract in `ai/CONTRACT.md` (new section "Live server") is kept.

Frames (every frame has `"t"`; unknown types and fields are ignored by all sides):

- `hello` (first frame, within 5 s): `{"t":"hello","v":1,"token":"utb_…","roles":["screen"|"controller"],
  "client":"tv|phone|web|extension","name":"Living room TV","tools":[…],"mic":bool,"speaker":bool}`. The token rides
  in the frame, never in the URL, because a browser cannot set a header on a WebSocket. Browser clients are also held
  to an `Origin` allow-list. Answer `welcome`: `{"device_id","user","voice":{…consent of this device},"peers":[{device_id,
  name,roles,client,focus?}],"server_time_ms"}` or `error` and close (`unauthorized`, `voice_off`, `too_many`).
- `focus` (screen → server, on change, debounced 300 ms, and every 5 s while playing):
  `{"t":"focus","seq":n,"screen":"player|browse|menu|search|other","video":{VideoMeta subset}|null,"position_s",
  "playing":bool,"rate","cut":{"active":bool,"label","part","parts","preset_id"|"request_id"}|null,
  "captions":{"track"}|null,"view":"summary|answer|cuts|none","at_ms"}`. The server keeps only the latest per screen,
  in memory, and extrapolates the position from `at_ms`, `playing` and `rate`.
- `listen` (controller → server): `{"t":"listen","id","state":"start|end|cancel","format":"audio/webm;codecs=opus|
  audio/wav","target":device_id|null,"t0_ms"}`. Binary frames between `start` and `end` are that utterance. Limits:
  30 s, 2 MiB, one utterance per controller at a time. `say` is the same without audio: `{"t":"say","id","text"}`
  (typed commands, tests, and the evaluation runner).
- `heard` (server → all of the user's devices): `{"t":"heard","id","state":"listening|transcribing|understood|failed",
  "text"?,"tool"?,"message"?}`. This is what lets the TV show "Listening…" and the words.
- `command` (server → one screen): `{"t":"command","id","tool","args":{…},"origin":{"device_id","kind":"voice|text"},
  "expires_ms","confirm":{"text","eta_s"?}|null}`.
- `ack` (screen → server): `{"t":"ack","id","state":"received|confirm_shown|started|done|failed|refused","message"?,
  "data"?}`. `received` is sent before anything else is done. `started` is the end state of a long action (a cut build
  that the existing follower will announce); `done` of an instant one.
- `reply` (server → devices): `{"t":"reply","id","text","more":bool,"speak":bool}` followed, when `speak`, by binary
  audio frames to devices with `speaker` and an `"t":"reply_end"`.
- `ask` / `answer`: a clarifying question or a confirmation: `{"t":"ask","id","text","options":[…],"expires_ms"}`;
  any controller or the screen answers `{"t":"answer","id","option"}`; a spoken yes, no or option name within the
  window is matched by the fixed-phrase matcher.
- `ping` / `pong` every 20 s with the sender's clock; a side silent for 45 s is dropped.

Rules:

- **Delivery.** A command is sent once. No `received` within 2 s: the controller is told "The TV did not answer" and
  the command is dead. A command is never replayed after a reconnect and expires 10 s after it was made: a late
  "pause" must not fire. Screens remember the last 50 ids and ignore a repeat.
- **Target.** The target is the screen the controller pinned, else the user's only connected screen, else the one that
  is playing, else the one whose focus changed last within 10 minutes. Two playing screens and no pin: one `ask`
  ("Living room or Bedroom?"). A screen only receives tools it listed in `hello`.
- **Several controllers.** Every device of the user sees `heard`, the outcome and `reply`, so a second phone or the TV
  shows the same state. Commands to one screen are handled one at a time, at most 3 waiting; more is refused as busy.
- **Offline.** No screen connected: the controller gets "The TV is not connected" at once (text, and speech when on).
  Nothing is queued for later. Backend unreachable: player tools still work; tools that need it answer "The server is
  not reachable". Live server unreachable: clients retry with backoff (1 s to 30 s, jitter) and every existing feature
  works as today; the Talk button says voice is unavailable.
- **When connected.** The TV connects only while voice is on for the device and the app is in front. The phone app
  connects while it is in front, or always in robot mode (foreground service). The phone page connects while its Talk
  page is open.
- **Limits.** 8 connections per user, 20 utterances per minute and 30 minutes of audio per day per user (config),
  frames over 64 KiB close the socket.

### 2.4 The live server and the backend

- Token check: the live server calls `GET /v1/me` with the device's own token and caches the answer for 60 s; a revoked
  device is out within a minute. `GET /v1/me` gains `"device":{"id","name"}`, `"voice":{"enabled","listen_mode",
  "speak","retention_days"}` and `features.voice`. It holds no user table of its own.
- Acting for the user: when the live server needs the backend (history, a question), it sends the token of the device
  that spoke. It has no privilege of its own and no admin token.
- New backend routes, all additive: `PUT /v1/me/devices/{id}/voice` (consent and modes per device, also on the Devices
  page), `PUT /v1/me/voice` (retention, the all-off switch), `POST /v1/voice/commands` (the live server files one record
  after a command ends), `GET /v1/voice/commands?limit=` and `DELETE /v1/voice/commands[/{id}]` (history page),
  `position_s` and `window_s` on `POST /v1/videos/{id}/ask` (2.8). New tables `device_voice` and `voice_commands`
  (text, tool, arguments, outcome, the timestamps of 2.5, no audio).
- `/setup.json` gains optional `realtime_url`, built from `server.public_base_url` and `[voice] realtime_path` (`/rt`).
- Deployment is the owner's pipeline: a second service next to the backend and a proxy rule for `/rt/` with WebSocket
  upgrade. Filed as a task in the operations repository at checkpoint 2; nothing runs on a development machine.

### 2.5 Latency budgets and how they are measured

Marks, all stamped by the live server unless noted; client marks are converted with the clock offset from `ping`:

| Mark | Event |
|---|---|
| t0 | end of speech on the client (Talk released, or the endpoint of 2.6) |
| t1 | last audio frame received |
| t2 | text back from speech-to-text |
| t3 | tool decided (matcher or model), arguments valid |
| t4 | `command` written to the screen's socket |
| t5 | `ack received` |
| t6 | `ack done` or `started` (the TV has acted and shown its confirmation) |
| t7 | first audio frame of the spoken reply written to a speaker device |

| Hop | Budget, half of the time | Budget, 9 of 10 | Sits in | Note |
|---|---|---|---|---|
| t0→t1 capture tail | 100 ms | 250 ms | client, network | audio is streamed while speaking; in wake-word mode the endpoint wait (700 ms of silence) comes before t0 and is reported separately |
| t1→t2 speech-to-text | 400 ms (short), 600 ms (a sentence) | 900 ms | gateway engine | one request per utterance; the gateway route is not streaming |
| t2→t3 fixed phrases | 5 ms | 10 ms | Go | no model |
| t2→t3 intent model | 600 ms | 1,200 ms | gateway engine | about 700 tokens in, at most 120 out |
| t3→t5 push | 50 ms | 150 ms | Go, network | |
| t5→t6 TV acts | 150 ms | 300 ms | TV app | player tools and starting a request; not the build itself |
| **t0→t6 simple** | **0.7 s** | **1.5 s** | | |
| **t0→t6 open** | **1.5 s** | **2.5 s** | | |
| t3→t7 speech out | 500 ms | 1,000 ms | gateway engine, Go | replies are one or two sentences |
| live server's own time, summed over hops | 10 ms | 20 ms | Go | t1→t4 minus engine time |

Every engine number above is a guess until checkpoint 0 (engines alone) and checkpoint 5 (whole path).

Measurement: each command's marks are part of its history record and of a `GET /rt/v1/stats` answer (admin token:
count, and the 50th, 90th and 99th percentile per hop over the last 1,000 commands, per tool family). CI runs a
benchmark with fake engines that answer after fixed delays and fails if the server's own time exceeds 20 ms at the 99th
percentile on loopback. Checkpoint 5 replays the recorded audio set through the real path against a test screen and
writes the table into the plan and `realtime/fixtures/voice/CHOICE-<date>.md`. A hop over its 9-of-10 budget is a named
finding with an owner (engine choice, prompt size, network), not a reason to move code between languages unless the
live server's own row is the one that fails.

Things done for speed inside those budgets: audio relayed as it arrives; a kept-alive connection pool to the gateway,
warmed on `listen start`; the focus snapshot taken at `listen start` and again at t2; the fixed-phrase matcher tried
first; `heard` frames sent at start, t2 and t3 so the screen changes within 150 ms of each.

### 2.6 Speech in

- Two entries, one engine alias. Live commands: audio frames to the live server, which posts the finished utterance to
  the gateway's `/v1/audio/transcriptions` under `[speech] alias` (its own config key of the same name). Dictation into
  a text box (#176 custom cut on the TV, #177 comments, the phone page's Speak): `POST /v1/speech`, unchanged. The TV's
  capture component of #176 is written once and feeds either.
- Formats: browsers send `MediaRecorder` chunks (webm/opus, or m4a on Safari); native clients send 16 kHz mono PCM as
  WAV (32 kB/s, fine on the LAN and the tailnet; Opus in the native app is a later saving, not planned). The live
  server never decodes audio; it concatenates and forwards with a decoder-friendly file name, as `speech.py` does.
- End of speech is decided by the client: release of Talk, or in hands-free mode R2T4's `PromptRecorder` with the
  silence wait lowered from 1,500 ms to 700 ms and the 15 s cap kept (both settings; checkpoint 10 tunes them on the
  recorded set). No server-side voice detection.
- Language: the `[speech] language` hint, per user later if decision 11 adds a language.
- Platform recogniser: only on a TV where #176's probe finds no usable raw audio and the owner picks "use the TV's own
  recogniser" for that device; the text then enters as `say`. Off by default and labelled as Google's.
- Wake word (robot mode only): an interface `WakeWordEngine` in the phone library with three implementations: none
  (tap or Talk), sherpa-onnx keyword spotting, and Porcupine in a `private` build flavour only. The public flavour has
  no Picovoice code. The bar for switching an engine on by default, measured in checkpoint 10 on the old phone one
  metre from the TV: at most 1 false wake per hour of normal-volume TV speech over 3 hours, and at least 9 of 10 wakes
  caught in quiet and 8 of 10 with the TV playing. Below the bar: robot mode is tap-to-talk with spoken replies.
- TV microphone: gated by #176's probe (inputs listed, 3 s recorded from each source). A device whose best input fails
  the probe gets no mic button and reports `mic:false`.

### 2.7 Audio while listening

Policy per screen, setting `voice.duck` with the values `auto` (default), `duck`, `pause`, `off`. In `auto`: when the
utterance comes from the TV's own microphone the player pauses on `heard listening` and resumes on `understood` or
`failed`, unless the command itself was play or pause; when it comes from another device the player volume drops to
20 % for the same span; when the TV's output is a headset or Bluetooth audio (`AudioManager.getDevices`) nothing
changes. No echo cancellation and no mixing are attempted (owner: an edge case). A spoken reply on the TV's speakers
uses the same span rules.

### 2.8 The command model

A fixed tool list. The model chooses one tool and fills its arguments, or asks one question. It never composes steps,
never sees a URL, and cannot name a video other than the one in focus.

| Tool | Arguments | Runs | Confirm |
|---|---|---|---|
| `play`, `pause` | none | TV player | no |
| `seek` | `to_s` or `by_s` (signed) | TV player | no |
| `next_part`, `previous_part` | none | TV cut controller (plain chapter or 10 s step when no cut is on is not guessed: answers "No cut is on") | no |
| `cut_off`, `cut_on` | none | TV cut controller | no |
| `cut_preset` | `preset_id` from the focus video's preset list, `mode?` | TV → `POST /v1/videos/{id}/cuts` | only for `watched` |
| `cut_custom` | `prompt` (the user's own words, at most 2,000 characters), `mode?` | same | only for `watched` |
| `captions_hq` | `force?` | TV → `POST /v1/videos/{id}/captions` | when from audio and the video is over 30 min |
| `summary` | `prompt_key?` from the prompt list | TV summary view | no |
| `research` | `kind` or `question` | TV → research request (only while `features.research`) | yes |
| `ask_video` | `question` | backend `ask` with position; answer as `reply` | no (yes if it would use the cloud) |
| `show_more`, `close_view`, `scroll` | `direction?` | TV text view | no |
| `cancel` | none | drops the pending question, or stops the request just started | no |
| `clarify` | `text`, `options` (at most 4) | `ask` frame | n/a |
| `none` | `say` | a short reply ("I can't do that here") | n/a |

- Two stages. Stage 1, no model: a table of normalised phrases and small patterns for `play`, `pause`, `seek` ("back
  30 seconds", "go to 12 minutes"), `next_part`, `previous_part`, `cut_on`, `cut_off`, `show_more`, `close_view`,
  `cancel`, yes and no. Stage 2, the `[voice.intent]` model (alias `fast`) with a system prompt listing the tools, the
  focus (screen, title, channel, duration, position, cut state, preset ids and labels, prompt keys and labels, feature
  flags) and the text; it answers one JSON object `{"tool","args"}`.
- Validation in the live server: the tool exists and the target screen listed it; arguments match the tool's schema;
  ids are in the focus lists; numbers are inside the video. One repair round naming the fault; then `none` with "I did
  not understand that". Title, channel and labels are untrusted text: they are quoted in the prompt as data, and since
  no tool deletes, pays or leaves the focused video, a hostile title can at worst pick a wrong harmless tool or a
  confirmable one.
- Confirmation is decided by the server from the tool table and the focus, never by the model. The screen shows the
  text with OK and Back; a spoken yes or no within 15 s counts. No answer cancels.
- A clarifying question is asked at most once per command and kept 30 s; the next utterance is read as its answer first.
- Without focus on a video (browse with no card focused, settings): video tools answer "Focus a video first".
- Long results reach the user through the paths that exist: the cut follower's announcement, the summary view, the
  Inbox (#160) and research's own announcement. The command's own outcome is only "started".

### 2.9 Models per step

| Step | Alias | Fallback | Why |
|---|---|---|---|
| Speech to text | `[speech] alias` (Whisper or nemotron-stt on the small engine) | none: "Speech service is busy" | own infra only (#188) |
| Stage 1 | no model | | zero cost, zero wait, cannot be wrong in new ways |
| Stage 2 intent | `fast` | `coder` after a failed repair round or when `fast` is busy | short structured answer; the big engine is scarce |
| `ask_video` | `coder` | `[voice.ask] fallback`, empty by default; the cloud alias only if decision 6's alternative is taken | needs the excerpt and reasoning; later pictures |
| Speech out | `[voice.tts] alias` (kitten-tts) | none: text only | |
| Cuts, captions, summary, research | unchanged per-feature config | | voice only starts them |

Measurement and the rule (checkpoint 5): on the text set of 2.13, each of `fast` and `coder` as stage 2. Pick `fast`
if it reaches the bars (at least 95 % of player-family lines, 90 % overall, no costly tool without confirmation, at
most 2 % wrong tool that changes playback) within the intent budget; else `coder` if it does; else stop and report,
with the cloud alias measured as a third column for the owner's decision. Per call the record holds engine seconds,
tokens and dollars as the gateway reports them (zero on local engines).

### 2.10 The TV as a screen

New classes in `common/.../utubot`: `UtubotLive` (one OkHttp WebSocket on the existing client's settings, reconnect,
heartbeat), `UtubotFocusReporter` (builds `focus` from `UtubotUiHost`, the focused card, the player's video, position
and state and the cut controller; debounced), `UtubotCommandExecutor` (a table from tool to the same methods the menu
and the player buttons call; runs on the main thread; sends `received` first), `UtubotVoiceOverlay` (the mic symbol,
"Listening…", the heard text, a confirmation or question with OK and Back, a short reply card; never takes focus
except for a question), `UtubotVoiceSettings` (the switch, `voice.duck`, spoken replies). Hooks in upstream files stay
small and are listed in `ai/APP_INTEGRATION.md`. A command while a video plays does not stop it unless the tool is
`pause` or the duck policy says so. With the TV microphone (checkpoint 9) the TV is also a controller: #176's capture
component streams to `UtubotLive` instead of posting to `/v1/speech`.

### 2.11 The phone app

- Location and build: `phone/`, its own Gradle build (current Android Gradle Plugin, Kotlin, Compose, minSdk 26), not
  a module of the TV build, which needs sibling checkouts and an old toolchain. Modules: `phone/core` (plain Kotlin
  and Android library: setup import and pairing against the existing routes, the live client, the recorder and prompt
  recorder from R2T4, `WakeWordEngine`, settings; unit tests on the JVM with a fake socket) and `phone/app` (Compose).
- Identity: name u·tubot, id `dev.utubot.phone`, the brand assets of `assets/brand/`, no backend address in the tree,
  HTTPS except for private addresses (the TV's rule; R2T4's blanket cleartext flag goes).
- Classic mode: a Talk screen (what the TV shows, the Talk button, the heard text, the outcome, a target picker when
  there are two screens) and the existing web UI in a WebView signed in with the device token (`POST /v1/auth/login
  {"token"}`), so the cut sheet, jobs and prompts are not written twice. The app is also a share target that opens the
  cut sheet for the shared link, as the installed page does.
- Robot mode: R2T4's foreground service with the microphone type only, a permanent notification, wake word or tap,
  spoken replies, a screen that can stay on and dim. The camera and the ambient upload code are copied but compiled
  out of the public flavour until a later decision (Part 1, decision 8).
- Release: a `phone` job in CI (unit tests, lint, debug build) and a `phone` leg in `utubot-release.yml` (signed APK per
  merge that touches `phone/`, its own version file). The backend's app channel learns a second app
  (`GET /app/phone/update.json`, `utubot app sync-github` reads both). The first public release waits for the owner.

### 2.12 Clients (parity)

- TV app: screen, and controller once it has a microphone (2.10).
- Phone page (web UI): controller. A "Talk" page with the button, the focus line and the heard text (checkpoint 4).
- Phone app: controller, classic and robot (2.11).
- Extension: its row is added to the parity matrix of `ai/BROWSER_EXTENSION_PLAN.md` in checkpoint 1. Intended: the tab
  that plays is a screen for the player and cut tools and the panel has a Talk button. Whether an MV3 background may
  hold a WebSocket under the extension's own rules (no state in memory, nothing that outlives a request) is not known;
  checkpoint 12 starts with that check on Firefox and Chromium. If it fails, the socket is held by the panel page while
  it is open, or the row becomes an exception in the contract's "Clients" section with this reason.

### 2.13 Privacy and consent (#188)

- Off by default per device. Switching voice on shows what it means (which microphone, where the sound goes, what is
  kept) and is stored in `device_voice`. The live server refuses `listen` from a device without it.
- Indicator: the TV shows the mic symbol while any `listen` of the user is open, whichever device holds the microphone.
  The phone app shows it in the app and, in robot mode, in the permanent notification; Android adds its own indicator.
- Stored: no audio, anywhere. The live server holds an utterance in memory until the engine answered and logs only
  device, bytes, duration and the marks. The command text and outcome are kept `retention_days` (30; 0 keeps nothing)
  and can be read and deleted on a History page. The 40 evaluation recordings are made by an explicit "Record for
  evaluation" switch that is off again after the session.
- Where it is processed: the gateway's local engines. The cloud alias never receives audio; it receives text only if the
  owner turns on the fallback of decision 6. The platform recogniser is a per-device choice labelled as Google's.
- Off switch: per device on the device; all devices on the Devices page and by voice-independent means (the TV setting).
  The all-off switch makes the live server close every socket of the user's microphones within the 60 s cache window.
- Other people in the room are covered by the indicator and by push-to-talk being the default; open listening exists
  only in robot mode with a wake word.

### 2.14 Failures and fallbacks

| Case | What the user gets |
|---|---|
| Speech engine busy or down | "Speech service is busy, try again" on the controller and the TV; nothing retried silently |
| Empty or unintelligible audio | "I did not catch that" |
| Intent model busy | player phrases still work (stage 1); others: "Busy, try again" after the fallback alias also failed |
| TV not connected, or no `received` in 2 s | "The TV is not connected" / "The TV did not answer" |
| Tool not possible here (no cut on, live stream, no transcript) | the TV's own message for that action, passed back in `ack` |
| Confirmation not answered in 15 s | cancelled, said once |
| Live server down | Talk says voice is unavailable; menus, cut sheet and every feature work as today |
| Owner later prefers one service | the frames of 2.3 are transport-neutral; the recorded fallback is the same contract served by the backend. Not built |

### 2.15 Evaluation

- Text set, committed (`realtime/fixtures/voice/commands.jsonl`): 120 lines of `{focus, text, expect:{tool, args
  matcher, confirm}}`, written for this plan: 40 player lines with paraphrases, 30 cut lines (presets by label,
  descriptions, modes), 20 for captions, summary and research, 15 questions, 15 that must end in `clarify` or `none`
  (no focus, another video named, nonsense, a hostile title in the focus). Scored per family: tool match, argument
  match, confirmation correct.
- Sound set, owner-recorded and not committed (kept on the owner's server): 40 of those lines spoken, 20 in quiet and 20
  with the TV playing at normal volume, through the Talk page and later the TV microphone. Scored end to end, with the
  word error of the transcript reported beside the tool score so a miss can be blamed on the right step.
- The runner (`utubot-rt eval`) drives `say` or replays audio against a scripted test screen and prints the table and
  the latency percentiles of 2.5. In CI it runs the text set against scripted model answers only.

### 2.16 Tests (never YouTube, never a real model, never a real microphone)

- Live server: Go unit tests for the matcher, validation, target choice, confirmation, expiry and replay protection;
  socket tests with an in-process fake screen and fake controllers (round trip, offline screen, two controllers, two
  screens, reconnect, limits, a revoked token); fake speech, intent and speech-out engines behind `httptest`; the
  loopback benchmark of 2.5; a test that the data directory stays empty after an utterance.
- Backend: `test_voice_api.py` (consent, history, retention, the `me` and setup additions, `ask` with a position),
  the route-auth enumeration, the additive-migration test, `scripts/emulator_mock_backend.py` gains the voice routes.
- TV: unit tests for the focus reporter, the executor's table (every tool to its action, unknown tool refused), the
  overlay model and duck policy; an emulator run against the mock backend and the live server in fake-engine mode on
  loopback, recorded in `docs/development.md`.
- Phone: JVM tests for the core module; an instrumented smoke test on an emulator with a fake socket.
- Extension: with its checkpoint, e2e on the stand-in pages against the live server in fake-engine mode.

## 3. New and changed files

- New: `realtime/` (Go module, `cmd/utubot-rt`, `internal/{ws,session,intent,engines,backend,config,web}`, fixtures,
  `AGENTS.md`, `README.md`, `DEVLOG.md`, `THIRD_PARTY.md`), `phone/` (`core`, `app`, Gradle files, `AGENTS.md`),
  TV classes of 2.10 with tests, `ai-backend/src/utubot/voice.py` and `tests/test_voice_api.py`, web UI pages `talk.js`
  and `history.js`.
- Changed: `ai/CONTRACT.md` (section "Live server", additions to `me`, setup, `ask`, "Clients"), `ai/APP_INTEGRATION.md`,
  `ai/BROWSER_EXTENSION_PLAN.md` (matrix row), `ai-backend` (`db.py`, `app.py`, `webroutes.py`, `config.py`,
  `config.example.toml`, `appchannel.py`), `scripts/emulator_mock_backend.py`, `.github/workflows/utubot-ci.yml` and
  `utubot-release.yml` (jobs `realtime` and `phone`), root `AGENTS.md` (the two new directories), `docs/server.md`,
  `docs/development.md`.

## 4. Checkpoints

One pull request each, each tested as section 2.16 says before review and ending with a clean-context review. Voice
sits behind `[voice] enabled` on the backend (default `false`) and the absence of `realtime_url`, so the rollback of
any checkpoint is that switch or a revert with no database step. Tiers as in the other plans.

| # | Scope | Done when | Tier | Issue | Needs owner |
|---|---|---|---|---|---|
| 0 | Gates, no code: decisions recorded here; the gateway's live alias list with the backend's key (speech, `fast`, `coder`, speech out) and a timed probe of each (10 short clips for speech, 10 intent prompts, 5 sentences out); the backend's event-loop lag on the owner's server; WebSocket through the proxy; the infra task filed | the numbers replace the guesses of 2.5 and 5.2; anything missing is named with who must act | n/a | #180 | decisions; "yes, MIT" |
| 1 | Backend and contract: `features.voice`, `me` and setup additions, consent and history tables and routes, Devices page switches, History page, mock routes, contract text, parity row | old clients unchanged (replayed in a test); consent and history lifecycle pass | Fast | #188, #181 | |
| 2 | Live server without models: skeleton from R2T4, sockets, `hello` with the backend check, focus store, target choice, `say` with stage 1 only, `command`, `ack`, expiry, several clients, offline, limits, stats, the loopback benchmark, the CI job | the socket tests pass; a scripted controller pauses a scripted screen; the server's own time is under 20 ms at the 99th percentile | Heavy | #181 | deploy and proxy rule |
| 3 | TV as a screen: live client, focus reporter, executor for the player and cut tools, overlay, settings and consent | unit tests; emulator recording: typed `say` commands pause, seek, change part and start a custom cut on the focused video while it plays | Heavy | #183 | |
| 4 | **First usable step.** Audio frames, speech-to-text, stage 2 with validation, confirmation and one clarifying question; the Talk page of the web UI; the text set and its runner | text set passes in CI with scripted answers; on the owner's server, holding Talk on the phone and saying "make a cut that …" starts that cut on the TV's focused video, and "pause" pauses it | Heavy | #182, #184 | try it; 10 minutes of recordings |
| 5 | Measurement and model choice: text and sound sets against the real engines; `CHOICE-<date>.md`; budgets and defaults corrected | the tables of 2.5 and 2.9 hold measured numbers; a pick by the rule of 2.9, or stop and report | Heavy | #182 | |
| 6 | Phone app, classic mode: `phone/` from R2T4, identity, setup and pairing, Talk screen, WebView, share target, CI and release leg, second app in the app channel | JVM and smoke tests; a signed build installs, pairs and drives the TV like the Talk page | Heavy | #180, #184 | a phone; go for the release |
| 7 | Replies: reply card, `show_more`, speech out to speaker devices, `summary`, `captions_hq`, `research` tools; Inbox and auto-scroll used when present | a summary asked by voice opens and scrolls; a spoken reply starts within budget on the phone | Fast | #186 | |
| 8 | Questions about the video: `ask` with a position, the excerpt window, answers that name the time, the `ask_video` tool, 15 question lines scored | the question lines pass their bar; an answer shows on the TV and is spoken on the phone | Heavy | #187 | |
| 9 | TV microphone: after #176's probe and capture component; mic button, streaming from the TV, the duck and pause policy, headset detection, no-mic devices | on the owner's TV: a command spoken to the TV with the video paused works; with a failing probe no button shows | Heavy | #185 | the TCL TV |
| 10 | Robot mode: foreground service, tap or wake word behind the interface, the open engine's bake-off against the bar of 2.6, endpoint tuning, spoken replies, notification | the bar's table is recorded; robot mode works hands-free, or tap-to-talk if the bar fails | Heavy | #184 | an old phone near the TV |
| 11 | Privacy finish: retention job, all-off switch end to end, the empty-data-directory audit on the deployed server, docs | every line of 2.13 has a test or a recorded check | Fast | #188 | |
| 12 | Extension: the background-socket check, then screen and Talk button, or the recorded exception | e2e on the stand-in pages; the matrix row is tied to tests or to the contract's exception | Heavy | #189 | |
| 13 | Owner's real-device pass and switch-on: each tool family used from the phone app and the TV, findings fixed or filed, defaults set | recorded in the devlog | Fast | #189 | an evening |

Order: 0; then 1 and 2 side by side; 3 and 4 after 2 (3 needs only the contract and the live server in fake mode);
5 after 4. 6 may start once 2 has landed but shares the one Android build slot with 3 and 9. 7 and 8 after 5. 9 waits
for #176. 10 after 6. 11 any time after 4. 12 after 5. 13 last. #177 (voice comments) stays in the backlog and reuses
`POST /v1/speech`, not the live path.

Estimates from the measured flow history (half under 6.7 h, four of five under 26 h, start to merge): checkpoints 1 to
4, about 27 h of flow time at the median, about 46 h if one of the four runs long; checkpoints 1 to 13, about 90 h at
the median and about 150 h with two or three long ones. 2, 3 and 6 are the likeliest long ones (new toolchains here).

## 5. Verified, and not

### 5.1 Verified (read; sources in section 1)

- The backend already has per-device tokens, pairing, a dictation route that stores nothing, and the request and
  announcement pattern a voice-started cut ends in. It has no push channel.
- The TV app has one place per action (`UtubotMenu`, `UtubotCutController`) and declares `RECORD_AUDIO`.
- R2T4's Android capture, endpoint and service code exists and ran for hours on an old phone; its server's prompt path
  is a placeholder; neither part has tests or authentication; the repository has no licence file.
- u·tubot is a public MIT repository with hosted CI; R2T4's Go module needs Go 1.24.
- The licence texts quoted in 1.3.

### 5.2 Could not be verified from here

- Every engine time in 2.5: nothing was sent to a model. Whether the gateway has a speech-out route and which alias
  names this client may use (checkpoint 0).
- Whether `fast` holds a one-object JSON answer over the focus prompt (checkpoint 4 with scripted answers, 5 for real).
- The backend's event-loop lag under normal use (checkpoint 0); the argument of 2.2 rests on the design, not on a number.
- WebSocket upgrade through the owner's proxy and tailnet relay (checkpoint 0).
- Raw microphone capture on the owner's TV (#176's probe) and which OkHttp version the TV build forces (WebSocket
  needs 3.5 or newer; checked first in checkpoint 3).
- Picovoice's free-plan limits, keyword file expiry and prices; the licences of sherpa-onnx's keyword models
  (checkpoint 10, before any model file is committed).
- Whether an MV3 background can hold the socket under the extension's rules on both browsers (checkpoint 12).
- kitten-tts's speed and whether its voice is good enough to leave on (checkpoint 0 and the owner's ear).
