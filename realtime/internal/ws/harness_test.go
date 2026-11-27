package ws_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"

	"github.com/evrenesat/u-tubot/realtime/internal/backend"
	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/session"
	"github.com/evrenesat/u-tubot/realtime/internal/stats"
	"github.com/evrenesat/u-tubot/realtime/internal/ws"
)

const waitFor = 3 * time.Second

// fakePython stands in for the Python backend: GET /v1/me and POST /v1/voice/commands.
type fakePython struct {
	mu      sync.Mutex
	tokens  map[string]fakeMe
	records []fakeRecord
	down    bool
	meCalls int
}

type fakeMe struct {
	user, device, name string
	voiceFeature, on   bool
	revoked            bool
}

type fakeRecord struct {
	token string
	body  map[string]any
}

func (f *fakePython) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if f.down {
		http.Error(w, "down", http.StatusBadGateway)
		return
	}
	me, ok := f.tokens[token]
	if !ok || me.revoked {
		http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
		return
	}
	switch r.URL.Path {
	case "/v1/me":
		f.meCalls++
		body := map[string]any{"user": me.user, "features": map[string]any{"voice": me.voiceFeature}}
		if me.voiceFeature {
			body["device"] = map[string]any{"id": me.device, "name": me.name}
			body["voice"] = map[string]any{"enabled": me.on, "listen_mode": "push", "speak": false, "retention_days": 30}
		}
		_ = json.NewEncoder(w).Encode(body)
	case "/v1/voice/commands":
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		f.records = append(f.records, fakeRecord{token, body})
		_ = json.NewEncoder(w).Encode(map[string]any{"stored": true, "id": "r1"})
	default:
		http.NotFound(w, r)
	}
}

func (f *fakePython) add(token, user, device, name string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.tokens[token] = fakeMe{user: user, device: device, name: name, voiceFeature: true, on: true}
}

func (f *fakePython) edit(token string, fn func(*fakeMe)) {
	f.mu.Lock()
	defer f.mu.Unlock()
	me := f.tokens[token]
	fn(&me)
	f.tokens[token] = me
}

func (f *fakePython) recordsSnapshot() []fakeRecord {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]fakeRecord(nil), f.records...)
}

type env struct {
	t     *testing.T
	py    *fakePython
	pySrv *httptest.Server
	cfg   config.Config
	hub   *session.Hub
	srv   *ws.Server
	http  *httptest.Server
	stats *stats.Store
}

// newEnv wires the real backend client, hub and server against the fake Python backend.
func newEnv(t *testing.T, tune func(*config.Config), understand session.Understander) *env {
	t.Helper()
	py := &fakePython{tokens: map[string]fakeMe{}}
	pySrv := httptest.NewServer(py)
	cfg := config.Default()
	cfg.BackendURL = pySrv.URL
	cfg.AdminToken = "admin-secret"
	cfg.AckTimeout = 300 * time.Millisecond
	cfg.CommandExpiry = 2 * time.Second
	cfg.HelloTimeout = 500 * time.Millisecond
	if tune != nil {
		tune(&cfg)
	}
	client := backend.New(cfg.BackendURL, cfg.BackendTimeout, cfg.AuthCache/4)
	store := stats.New(cfg.StatsWindow)
	hub := session.New(session.Options{Config: cfg, Recorder: client, Stats: store, Understand: understand})
	srv := ws.New(cfg, hub, client, nil)
	httpSrv := httptest.NewServer(srv.Handler())
	e := &env{t: t, py: py, pySrv: pySrv, cfg: cfg, hub: hub, srv: srv, http: httpSrv, stats: store}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), waitFor)
		defer cancel()
		srv.Shutdown(ctx)
		httpSrv.Close()
		pySrv.Close()
	})
	return e
}

func (e *env) wsURL() string {
	return "ws" + strings.TrimPrefix(e.http.URL, "http") + e.cfg.Path + "/v1/ws"
}

// tc is a scripted device: a socket with a goroutine collecting frames.
type tc struct {
	t      *testing.T
	c      *websocket.Conn
	frames chan map[string]any
	binary chan []byte
	err    chan error
}

func (e *env) rawDial(header http.Header) (*tc, error) {
	ctx, cancel := context.WithTimeout(context.Background(), waitFor)
	defer cancel()
	c, _, err := websocket.Dial(ctx, e.wsURL(), &websocket.DialOptions{HTTPHeader: header})
	if err != nil {
		return nil, err
	}
	d := &tc{t: e.t, c: c, frames: make(chan map[string]any, 512), binary: make(chan []byte, 16), err: make(chan error, 1)}
	go func() {
		for {
			typ, data, err := c.Read(context.Background())
			if err != nil {
				d.err <- err
				close(d.frames)
				return
			}
			if typ == websocket.MessageBinary {
				d.binary <- data
				continue
			}
			var f map[string]any
			if json.Unmarshal(data, &f) == nil {
				d.frames <- f
			}
		}
	}()
	e.t.Cleanup(func() { _ = c.CloseNow() })
	return d, nil
}

func (d *tc) send(v any) {
	d.t.Helper()
	data, _ := json.Marshal(v)
	ctx, cancel := context.WithTimeout(context.Background(), waitFor)
	defer cancel()
	if err := d.c.Write(ctx, websocket.MessageText, data); err != nil {
		d.t.Fatalf("write: %v", err)
	}
}

func (d *tc) sendBinary(b []byte) {
	d.t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), waitFor)
	defer cancel()
	if err := d.c.Write(ctx, websocket.MessageBinary, b); err != nil {
		d.t.Fatalf("write: %v", err)
	}
}

// next waits for the next frame accepted by match, skipping the others.
func (d *tc) next(match func(map[string]any) bool) map[string]any {
	d.t.Helper()
	timer := time.NewTimer(waitFor)
	defer timer.Stop()
	for {
		select {
		case f, ok := <-d.frames:
			if !ok {
				d.t.Fatalf("socket closed while waiting: %v", <-d.err)
			}
			if match(f) {
				return f
			}
		case <-timer.C:
			d.t.Fatal("timed out waiting for a frame")
		}
	}
}

func ofType(t string) func(map[string]any) bool {
	return func(f map[string]any) bool { return f["t"] == t }
}

func (d *tc) expect(t string) map[string]any { d.t.Helper(); return d.next(ofType(t)) }

// outcome waits for the outcome frame of a say id.
func (d *tc) outcome(id string) map[string]any {
	d.t.Helper()
	return d.next(func(f map[string]any) bool { return f["t"] == "outcome" && f["id"] == id })
}

// none asserts that no frame accepted by match arrives within a short while.
func (d *tc) none(match func(map[string]any) bool, wait time.Duration) {
	d.t.Helper()
	timer := time.NewTimer(wait)
	defer timer.Stop()
	for {
		select {
		case f, ok := <-d.frames:
			if !ok {
				return
			}
			if match(f) {
				d.t.Fatalf("unexpected frame %v", f)
			}
		case <-timer.C:
			return
		}
	}
}

// closedWith waits for the socket to end and returns the error code of the last error frame seen.
func (d *tc) closedWith() string {
	d.t.Helper()
	code := ""
	timer := time.NewTimer(waitFor)
	defer timer.Stop()
	for {
		select {
		case f, ok := <-d.frames:
			if !ok {
				return code
			}
			if f["t"] == "error" {
				code, _ = f["code"].(string)
			}
		case <-timer.C:
			d.t.Fatal("socket stayed open")
		}
	}
}

type helloOpts struct {
	roles  []string
	tools  []string
	name   string
	client string
	mic    bool
}

var playerTools = []string{"play", "pause", "seek", "next_part", "previous_part", "cut_on", "cut_off", "show_more", "close_view", "cancel", "research"}

// connect dials, says hello and returns the welcome frame.
func (e *env) connect(token string, o helloOpts) (*tc, map[string]any) {
	e.t.Helper()
	d, err := e.rawDial(nil)
	if err != nil {
		e.t.Fatal(err)
	}
	if o.client == "" {
		o.client = "test"
	}
	d.send(map[string]any{"t": "hello", "v": 1, "token": token, "roles": o.roles, "client": o.client, "name": o.name, "tools": o.tools, "mic": o.mic})
	return d, d.next(func(f map[string]any) bool { return f["t"] == "welcome" })
}

func (e *env) screen(token, name string) *tc {
	e.t.Helper()
	d, _ := e.connect(token, helloOpts{roles: []string{"screen"}, tools: playerTools, name: name, client: "tv"})
	return d
}

func (e *env) controller(token, name string) *tc {
	e.t.Helper()
	d, _ := e.connect(token, helloOpts{roles: []string{"controller"}, name: name, client: "phone"})
	return d
}

func playing(seq int, id string, isPlaying bool) map[string]any {
	return map[string]any{"t": "focus", "seq": seq, "screen": "player", "video": map[string]any{"id": id, "title": "A talk", "duration_s": 3600},
		"position_s": 120, "playing": isPlaying, "rate": 1, "view": "none"}
}

// sync makes sure everything this device sent before was processed by the server (frames of one socket are ordered).
func (d *tc) sync() {
	d.t.Helper()
	d.send(map[string]any{"t": "ping", "ts": 1})
	d.next(ofType("pong"))
}

func eventually(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(waitFor)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("timed out: %s", what)
}
