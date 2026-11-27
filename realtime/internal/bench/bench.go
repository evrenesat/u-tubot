// Package bench is the loopback benchmark of plan 2.5: scripted controllers say "pause" and "play" to scripted
// screens through a real WebSocket server on 127.0.0.1, and the report gives the live server's own time (the hop
// from the say frame being read to the command being written) at the 50th, 90th and 99th percentile.
// No engine, no model, no microphone: only the live server's code and the loopback network.
package bench

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/evrenesat/u-tubot/realtime/internal/backend"
	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/session"
	"github.com/evrenesat/u-tubot/realtime/internal/stats"
	"github.com/evrenesat/u-tubot/realtime/internal/ws"
)

// DefaultMaxP99 is the plan's budget for the live server's own time.
const DefaultMaxP99 = 20 * time.Millisecond

const (
	warmup        = 50
	stepTimeout   = 5 * time.Second
	benchSecret   = "bench-token"
	hubListenHost = "127.0.0.1:0"
)

// Options of a run.
type Options struct {
	Commands int
	Users    int
	Idle     int
}

// Default is a run that finishes in a few seconds.
func Default() Options { return Options{Commands: 3000, Users: 4, Idle: 200} }

// Result of a run.
type Result struct {
	Commands  int
	Server    stats.Percentiles
	Push      stats.Percentiles
	RoundTrip stats.Percentiles
	Elapsed   time.Duration
}

// Table prints the result for a log or a pull request.
func (r Result) Table() string {
	var b strings.Builder
	fmt.Fprintf(&b, "loopback benchmark: %d commands in %s\n", r.Commands, r.Elapsed.Round(time.Millisecond))
	fmt.Fprintf(&b, "%-34s %8s %8s %8s %8s\n", "hop", "p50 ms", "p90 ms", "p99 ms", "max ms")
	row := func(name string, p stats.Percentiles) {
		fmt.Fprintf(&b, "%-34s %8.3f %8.3f %8.3f %8.3f\n", name, p.P50, p.P90, p.P99, p.Max)
	}
	row("live server's own time (t_in to t4)", r.Server)
	row("push to ack (t4 to t5, loopback)", r.Push)
	row("say to ack done (controller clock)", r.RoundTrip)
	return b.String()
}

type fakeBackend struct{ users int }

func (f fakeBackend) Check(_ context.Context, token string) (backend.Identity, error) {
	// Tokens look like "bench-token:<user>:<device>".
	parts := strings.Split(token, ":")
	if len(parts) != 3 || parts[0] != benchSecret {
		return backend.Identity{}, backend.ErrUnauthorized
	}
	return backend.Identity{User: parts[1], DeviceID: parts[2], DeviceName: parts[2], VoiceOn: true, ListenMode: "push"}, nil
}

type client struct {
	c *websocket.Conn
}

func dial(ctx context.Context, addr, user, device string, roles, tools []string) (*client, error) {
	c, _, err := websocket.Dial(ctx, "ws://"+addr+"/rt/v1/ws", nil)
	if err != nil {
		return nil, err
	}
	hello := map[string]any{"t": "hello", "v": 1, "token": fmt.Sprintf("%s:%s:%s", benchSecret, user, device), "roles": roles, "client": "bench", "name": device, "tools": tools}
	data, _ := json.Marshal(hello)
	if err := c.Write(ctx, websocket.MessageText, data); err != nil {
		return nil, err
	}
	cl := &client{c: c}
	if f, err := cl.read(ctx); err != nil || f["t"] != "welcome" {
		return nil, fmt.Errorf("no welcome: %v %v", f, err)
	}
	return cl, nil
}

func (c *client) read(ctx context.Context) (map[string]any, error) {
	_, data, err := c.c.Read(ctx)
	if err != nil {
		return nil, err
	}
	var f map[string]any
	return f, json.Unmarshal(data, &f)
}

func (c *client) write(ctx context.Context, v any) error {
	data, _ := json.Marshal(v)
	return c.c.Write(ctx, websocket.MessageText, data)
}

// Run executes the benchmark.
func Run(o Options) (Result, error) {
	cfg := config.Default()
	cfg.BackendURL = "http://127.0.0.1:1"
	// The benchmark measures the server, not its limits.
	cfg.UtterancesPerMin = o.Commands*2 + 1000
	cfg.MaxConnsPerUser = o.Idle + 16
	store := stats.New(o.Commands + warmup*o.Users + 10)
	hub := session.New(session.Options{Config: cfg, Stats: store})
	srv := ws.New(cfg, hub, fakeBackend{users: o.Users}, nil)
	ln, err := net.Listen("tcp", hubListenHost)
	if err != nil {
		return Result{}, err
	}
	httpServer := &http.Server{Handler: srv.Handler()}
	go func() { _ = httpServer.Serve(ln) }()
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), stepTimeout)
		defer cancel()
		srv.Shutdown(ctx)
		_ = httpServer.Shutdown(ctx)
	}()
	addr := ln.Addr().String()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	var idle []*client
	for i := 0; i < o.Idle; i++ {
		c, err := dial(ctx, addr, "idle", fmt.Sprintf("idle-%d", i), []string{"controller"}, nil)
		if err != nil {
			return Result{}, err
		}
		idle = append(idle, c)
	}
	defer func() {
		for _, c := range idle {
			_ = c.c.CloseNow()
		}
	}()

	per := o.Commands / o.Users
	var wg, screens sync.WaitGroup
	var screenConns, controllers []*client
	var mu sync.Mutex
	var roundTrips []time.Duration
	errs := make(chan error, o.Users*2)
	start := time.Now()
	for u := 0; u < o.Users; u++ {
		user := fmt.Sprintf("user%d", u)
		screen, err := dial(ctx, addr, user, "tv", []string{"screen"}, []string{"play", "pause", "seek"})
		if err != nil {
			return Result{}, err
		}
		controller, err := dial(ctx, addr, user, "phone", []string{"controller"}, nil)
		if err != nil {
			return Result{}, err
		}
		focus := map[string]any{"t": "focus", "seq": 1, "screen": "player", "video": map[string]any{"id": "v1", "duration_s": 3600}, "position_s": 10, "playing": true, "rate": 1, "view": "none"}
		if err := screen.write(ctx, focus); err != nil {
			return Result{}, err
		}
		// A ping answered on the same socket proves the focus frame before it was processed.
		if err := screen.write(ctx, map[string]any{"t": "ping", "ts": 1}); err != nil {
			return Result{}, err
		}
		for {
			f, err := screen.read(ctx)
			if err != nil {
				return Result{}, err
			}
			if f["t"] == "pong" {
				break
			}
		}
		screenConns = append(screenConns, screen)
		controllers = append(controllers, controller)
		wg.Add(1)
		screens.Add(1)
		go func() { // the scripted screen: acknowledge at once, then done
			defer screens.Done()
			for {
				f, err := screen.read(ctx)
				if err != nil {
					return
				}
				switch f["t"] {
				case "command":
					id := f["id"]
					if screen.write(ctx, map[string]any{"t": "ack", "id": id, "state": "received"}) != nil ||
						screen.write(ctx, map[string]any{"t": "ack", "id": id, "state": "done"}) != nil {
						return
					}
				case "error":
					return
				}
			}
		}()
		go func() { // the scripted controller
			defer wg.Done()
			words := []string{"pause", "play", "back 30 seconds", "next part"}
			for i := 0; i < per; i++ {
				id := fmt.Sprintf("b%d", i)
				t0 := time.Now()
				text := words[i%2]
				if err := controller.write(ctx, map[string]any{"t": "say", "id": id, "text": text}); err != nil {
					errs <- err
					return
				}
				for {
					rctx, rcancel := context.WithTimeout(ctx, stepTimeout)
					f, err := controller.read(rctx)
					rcancel()
					if err != nil {
						errs <- fmt.Errorf("waiting for the outcome of %s: %w", id, err)
						return
					}
					if f["t"] == "outcome" && f["id"] == id {
						if f["state"] != "ok" {
							errs <- fmt.Errorf("command %s ended %v: %v", id, f["state"], f["message"])
							return
						}
						break
					}
				}
				mu.Lock()
				roundTrips = append(roundTrips, time.Since(t0))
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	elapsed := time.Since(start)
	for _, c := range append(screenConns, controllers...) {
		_ = c.c.CloseNow()
	}
	screens.Wait()
	close(errs)
	if err := <-errs; err != nil {
		return Result{}, err
	}

	var server, push []time.Duration
	for _, rec := range store.Records() {
		if d, ok := rec.Hops[stats.HopServer]; ok {
			server = append(server, d)
		}
		if d, ok := rec.Hops[stats.HopPush]; ok {
			push = append(push, d)
		}
	}
	return Result{
		Commands: len(server), Server: stats.Compute(server), Push: stats.Compute(push),
		RoundTrip: stats.Compute(roundTrips), Elapsed: elapsed,
	}, nil
}
