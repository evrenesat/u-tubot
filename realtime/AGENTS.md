# realtime/ agent guidance

`utubot-rt`: the live server of voice control (`ai/VOICE_CONTROL_PLAN.md`, sections 2.1 to 2.5). Go (1.27), standard library plus
`github.com/coder/websocket`. Read the plan, `ai/CONTRACT.md` ("Live server") and `DEVLOG.md` first.

- Layout: `cmd/utubot-rt` (serve, bench), `internal/{config,backend,proto,intent,session,ws,stats,bench}`. `session` holds all state behind one
  mutex and never blocks while holding it (`Conn.Send` only queues); `ws` is transport and the hello check; `intent` is the tool table,
  validation, the confirmation rule and the phrase matcher (stage 1); `backend` asks the Python backend who a token is (cached) and files history.
- The live server keeps no file and no database, and audio is never written anywhere: do not add either. Models and speech engines are
  later checkpoints; nothing here may call a real model, a microphone or YouTube, in tests least of all.
- Tests: `cd realtime && go vet ./... && go test -race -count=1 ./...`; the loopback benchmark is `go run ./cmd/utubot-rt bench` (fails over
  20 ms at the 99th percentile of the server's own time). Socket tests use a fake Python backend over `httptest`; scripted devices live in
  `internal/ws/harness_test.go`. A new frame, tool or rule gets a socket test and a line in `ai/CONTRACT.md`.
- Go: the pinned toolchain is in `.github/workflows/utubot-ci.yml` (`go-version`) and `go` in `go.mod`; keep both and the pinned action SHAs in step.
- No deployment from this directory: the operations repository owns the service and the proxy rule (evrenesat/evreniops#250).
- No personal host, token or key in the tree; examples use `utubot.example.com` and `127.0.0.1`.
