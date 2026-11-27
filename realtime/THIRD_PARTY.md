# Third-party code

## evrenesat/r2t4 (MIT, copyright 2026 Evren Özkan)

The live server grew from the Go server of the owner's R2T4 experiment (`server/`, licensed MIT on 26 November 2026,
[evrenesat/r2t4#22](https://github.com/evrenesat/r2t4/pull/22)). What was taken is the skeleton, not source lines: the entry
point's shape (flag handling, signal-driven graceful shutdown, a route table over `net/http`) in `cmd/utubot-rt/main.go` and
`internal/ws/server.go`, and the configuration loader's layout (defaults, file, command line and environment on top, one validation
step) in `internal/config/config.go`. R2T4's Connect-RPC services, file storage, plugin system and embedded admin page are not
carried over (plan 2.2 and 2.3). Each of the three files names its origin in its header.

The MIT notice of R2T4 applies to that origin:

> Copyright (c) 2026 Evren Özkan. Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
> rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to
> whom the Software is furnished to do so, subject to the conditions of the MIT licence as in the repository's `LICENSE`.

## github.com/coder/websocket v1.8.15 (ISC)

The one dependency besides the standard library: the WebSocket server and client (`internal/ws`, tests and the benchmark). Pinned in
`go.mod` and `go.sum`; no cgo.
