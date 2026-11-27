# utubot-rt, the live server

The real-time half of u·tubot's voice control ([plan](../ai/VOICE_CONTROL_PLAN.md), [wire contract](../ai/CONTRACT.md#live-server-addendum-2026-11-27)).
One WebSocket per device carries the focus a TV reports, the commands a phone or the TV itself sends, and the answers. The Python backend
stays the owner of accounts, consent and history; this service asks it who a token belongs to and files each finished command there.

State of this checkpoint (2 of 13): sockets, `hello` with the backend check, the focus store, target choice, typed commands (`say`) understood by
a phrase matcher with no model, `command` / `ack`, expiry, confirmation, several devices, offline answers, limits, statistics, a loopback
benchmark. Not yet: audio, speech-to-text, the intent model, speech out, any client.

```
cd realtime
go test -race -count=1 ./...
go run ./cmd/utubot-rt bench                      # server's own time on loopback, fails over 20 ms at p99
UTUBOT_RT_BACKEND_URL=http://127.0.0.1:8790 go run ./cmd/utubot-rt serve -config config.example.toml
```

`GET /rt/v1/health` answers without a token; `GET /rt/v1/stats` needs `UTUBOT_RT_ADMIN_TOKEN` as a bearer token. Configuration:
[config.example.toml](config.example.toml). Third-party code: [THIRD_PARTY.md](THIRD_PARTY.md).
