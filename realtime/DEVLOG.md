# realtime/ devlog

## 2026-11-27 (checkpoint 2 of the voice plan, issue #181)

- New Go module `realtime/` (`utubot-rt`), Go 1.22 and `github.com/coder/websocket` v1.8.12, grown from the shape of R2T4's server
  (`THIRD_PARTY.md`). The toolchain on the development host is Go 1.22.2 (system package, untouched); CI pins 1.22.12 through `actions/setup-go`.
- What it does: `GET /rt/v1/ws` with a `hello` check against `GET /v1/me` (60 s window, split so a revocation or a voice switch-off closes the
  socket within it), focus store with sequence numbers and position extrapolation, target choice (pin, only screen, playing, most recent
  focus, otherwise an `ask`), `say` with the stage 1 matcher (play, pause, seek by seconds/minutes/clock, parts, cut on/off, view and cancel
  phrases, yes/no), validation against the focus, confirmation decided from the tool table, `command` / `ack` with the 2 s `received` rule,
  10 s expiry, one command at a time per screen with 3 waiting, `revoke`, offline answers, per-user limits (8 sockets, 20 utterances a minute,
  30 minutes of audio a day, frame, utterance and text sizes), a history record per finished command with the speaker's token, statistics
  per hop and tool family, `/rt/v1/health`.
- `listen` is accepted and its limits enforced, but with no speech engine the audio is counted and dropped (never stored) and the user is told
  "Speech is not available on this server".
- Tests: 40 socket tests over a fake Python backend plus unit tests for the matcher, validation, config, statistics and the position
  extrapolation, all under `-race`; the loopback benchmark is a test and a CI step.
- Benchmark (3,000 commands, 4 controllers and 4 screens, 200 idle sockets): the server's own time, frame read to command written, is
  p50 0.008 ms, p90 0.033 ms, p99 0.08 ms; the budget is 20 ms.
- Found on the way: a read deadline on `coder/websocket` closes the socket before an error frame can be written, so the hello and idle limits are
  watchdog timers; a close handshake with a vanished peer waits 5 s, so a peer that is gone is closed at once.
- Decisions not in the plan: `outcome`, `peers` and `revoke` frames (the plan said the outcome and the peers reach every device without naming a frame),
  `say` takes the same optional `target` as `listen`, `expires_ms` is a time on the server's clock. The understanding stage runs under the hub's lock
  and must answer in microseconds; the model stage of checkpoint 4 has to run before the lock is taken.
- Not done here: deployment and the proxy rule (evrenesat/evreniops#250), the TV, any client.
