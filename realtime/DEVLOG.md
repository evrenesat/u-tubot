# realtime/ devlog

## 2026-11-27 (checkpoint 2 of the voice plan, issue #181)

- New Go module `realtime/` (`utubot-rt`), Go 1.27 and `github.com/coder/websocket` v1.8.15 (first written for 1.22 and 1.8.12; bumped in review), grown from the shape of R2T4's server
  (`THIRD_PARTY.md`). The development host's Go is 1.22.2 (system package, untouched); a Go 1.27.4 under /tmp is used locally and CI pins 1.27.4 through `actions/setup-go`.
- What it does: `GET /rt/v1/ws` with a `hello` check against `GET /v1/me` (60 s window, split so a revocation or a voice switch-off closes the
  socket within it), focus store with sequence numbers and position extrapolation, target choice (pin, only screen, playing, most recent
  focus, otherwise an `ask`), `say` with the stage 1 matcher (play, pause, seek by seconds/minutes/clock, parts, cut on/off, view and cancel
  phrases, yes/no), validation against the focus, confirmation decided from the tool table, `command` / `ack` with the 2 s `received` rule,
  10 s expiry, one command at a time per screen with 3 waiting, `revoke`, offline answers, per-user limits (8 sockets, 20 utterances a minute,
  30 minutes of audio a day, frame, utterance and text sizes), a history record per finished command with the speaker's token, statistics
  per hop and tool family, `/rt/v1/health`.
- `listen` is accepted and its limits enforced, but with no speech engine the audio is counted and dropped (never stored) and the user is told
  "Speech is not available on this server".
- Tests: 56 socket tests over a fake Python backend plus unit tests for the matcher, validation, config, statistics and the position
  extrapolation, all under `-race`; the loopback benchmark is a test and a CI step.
- Benchmark (3,000 commands, 4 controllers and 4 screens, 200 idle sockets): the server's own time, frame read to command written, is
  p50 0.008 ms, p90 0.033 ms, p99 0.08 ms; the budget is 20 ms.
- Found on the way: a read deadline on `coder/websocket` closes the socket before an error frame can be written, so the hello and idle limits are
  watchdog timers; a close handshake with a vanished peer waits 5 s, so a peer that is gone is closed at once.
- Decisions not in the plan: `outcome`, `peers` and `revoke` frames (the plan said the outcome and the peers reach every device without naming a frame),
  `say` takes the same optional `target` as `listen`, `expires_ms` is a time on the server's clock. The understanding stage runs under the hub's lock
  and must answer in microseconds; the model stage of checkpoint 4 has to run before the lock is taken.
- Not done here: deployment and the proxy rule (evrenesat/evreniops#250), the TV, any client.

## 2026-11-27 (review of the checkpoint 2 pull request)

- Backend sign-in budget: tokens are shape-checked (`utb_`, length) before any `/v1/me` call; upgrade attempts are limited per client address (last
  `X-Forwarded-For` entry); sockets waiting for a hello are capped; every call carries `X-Utubot-Client: realtime`; a device that cannot be re-checked
  for 10 minutes is closed (`not_verified`), and an old good answer is no longer served while the backend is down. The backend still needs its own
  bucket for that header (follow-up: #252).
- Limits live in a per-user limiter that survives reconnecting (evicted after a quiet day). Audio is charged on every exit of an utterance and a
  per-utterance timer ends one at 30 s; every exit sends `heard failed`, also when the controller disconnects or is replaced.
- Rate-limited frames are neither filed nor counted; history records go through a bounded queue with two workers and are dropped when it is full.
- A screen silent for 15 s is not playing; the understanding stage gets the focus aged and extrapolated. A resent `say` id is ignored (2 minutes).
- Smaller: clarifying questions are kept and answered, a spoken cancel of a confirmation goes through the same path as a no, unknown ack states are
  not receipts, only controllers answer confirmations, `slow_consumer` has its own code, focus relay is capped at 8 KiB, health shows no counts,
  a hello during shutdown is refused. Contract text corrected (cache numbers, error codes, `replaced` is terminal).
