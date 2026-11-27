// Package ws serves the control channel: it accepts WebSockets, runs the hello check against the backend, feeds the
// session hub and answers the stats and health routes. Skeleton (graceful shutdown, route table, JSON helpers)
// adapted from R2T4's server entry point, MIT, see THIRD_PARTY.md.
package ws

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/evrenesat/u-tubot/realtime/internal/backend"
	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/proto"
	"github.com/evrenesat/u-tubot/realtime/internal/session"
)

const (
	writeTimeout   = 5 * time.Second
	maxNameRunes   = 64
	maxClientRunes = 32
	randomIDBytes  = 6
)

// Server is the HTTP side of the live server.
type Server struct {
	cfg     config.Config
	hub     *session.Hub
	checker backend.Checker
	log     *slog.Logger

	mu       sync.Mutex
	active   int
	stopping bool
	drained  chan struct{}
}

// New builds the server around a hub and a token checker.
func New(cfg config.Config, hub *session.Hub, checker backend.Checker, log *slog.Logger) *Server {
	if log == nil {
		log = slog.Default()
	}
	return &Server{cfg: cfg, hub: hub, checker: checker, log: log, drained: make(chan struct{})}
}

// Handler returns the routes under the configured path (default /rt).
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET "+s.cfg.Path+"/v1/ws", s.serveWS)
	mux.HandleFunc("GET "+s.cfg.Path+"/v1/stats", s.serveStats)
	mux.HandleFunc("GET "+s.cfg.Path+"/v1/health", s.serveHealth)
	return mux
}

// Shutdown closes every socket and waits for the connection goroutines.
func (s *Server) Shutdown(ctx context.Context) {
	s.mu.Lock()
	s.stopping = true
	if s.active == 0 {
		close(s.drained)
	}
	s.mu.Unlock()
	s.hub.CloseAll(proto.ErrServerShutdown, "the live server is restarting")
	select {
	case <-s.drained:
	case <-ctx.Done():
	}
}

func (s *Server) enter() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.stopping {
		return false
	}
	s.active++
	return true
}

func (s *Server) exit() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.active--
	if s.stopping && s.active == 0 {
		close(s.drained)
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func (s *Server) serveHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "connections": s.hub.Connections()})
}

func (s *Server) serveStats(w http.ResponseWriter, r *http.Request) {
	if s.cfg.AdminToken == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "stats are not enabled"})
		return
	}
	got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if subtle.ConstantTimeCompare([]byte(got), []byte(s.cfg.AdminToken)) != 1 {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "admin token required"})
		return
	}
	writeJSON(w, http.StatusOK, s.hub.Stats().Report())
}

// conn is the hub's view of a socket: a bounded queue drained by one writer goroutine.
type conn struct {
	ws     *websocket.Conn
	mu     sync.Mutex
	out    chan []byte
	closed bool
	gone   bool
	code   string
	done   chan struct{}
}

func newConn(c *websocket.Conn, queue int) *conn {
	return &conn{ws: c, out: make(chan []byte, queue), done: make(chan struct{})}
}

// Send implements session.Conn.
func (c *conn) Send(v any) bool {
	data, err := json.Marshal(v)
	if err != nil {
		return false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return false
	}
	select {
	case c.out <- data:
		return true
	default:
		return false
	}
}

// Close implements session.Conn: an error frame, then the socket closes once the queue is written.
func (c *conn) Close(code, message string) {
	data, _ := json.Marshal(proto.New(proto.TError).With("code", code).With("message", message))
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return
	}
	c.closed, c.code = true, code
	select {
	case c.out <- data:
	default:
	}
	close(c.out)
}

// finish ends the queue without a frame (the peer is gone).
func (c *conn) finish() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.closed {
		c.closed, c.gone = true, true
		close(c.out)
	}
}

func (c *conn) writeLoop(ctx context.Context) {
	defer close(c.done)
	for msg := range c.out {
		wctx, cancel := context.WithTimeout(ctx, writeTimeout)
		err := c.ws.Write(wctx, websocket.MessageText, msg)
		cancel()
		if err != nil {
			_ = c.ws.CloseNow()
			for range c.out {
			}
			return
		}
	}
	c.mu.Lock()
	code, gone := c.code, c.gone
	c.mu.Unlock()
	if gone {
		_ = c.ws.CloseNow()
		return
	}
	status := websocket.StatusPolicyViolation
	if code == proto.ErrServerShutdown || code == proto.ErrReplaced {
		status = websocket.StatusGoingAway
	}
	_ = c.ws.Close(status, code)
}

func (s *Server) serveWS(w http.ResponseWriter, r *http.Request) {
	if !s.enter() {
		http.Error(w, "shutting down", http.StatusServiceUnavailable)
		return
	}
	defer s.exit()
	ws, err := websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: s.cfg.Origins})
	if err != nil {
		return
	}
	ws.SetReadLimit(int64(s.cfg.MaxFrameBytes))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	c := newConn(ws, s.cfg.OutQueue)
	go c.writeLoop(ctx)
	defer func() { c.finish(); <-c.done }()

	sess, rejected := s.hello(ctx, ws, c)
	if sess == nil {
		if rejected != "" {
			c.Close(rejected, rejected)
		} else {
			c.Close(proto.ErrBadHello, "no hello")
		}
		return
	}
	defer s.hub.Leave(sess)
	recheckCtx, stopRecheck := context.WithCancel(ctx)
	defer stopRecheck()
	go s.recheck(recheckCtx, sess)
	go s.pinger(recheckCtx, c)
	s.readLoop(ctx, ws, c, sess)
}

// hello reads and checks the first frame. A rejection code is returned for the error frame.
func (s *Server) hello(ctx context.Context, ws *websocket.Conn, c *conn) (*session.Session, string) {
	// A read that runs out of time closes the socket before an error frame could be written, so the deadline is a
	// watchdog that sends the frame and ends the connection instead.
	watchdog := time.AfterFunc(s.cfg.HelloTimeout, func() { c.Close(proto.ErrHelloTimeout, "no hello") })
	typ, data, err := ws.Read(ctx)
	if !watchdog.Stop() {
		return nil, "" // the watchdog fired: it already sent the error frame
	}
	if err != nil {
		return nil, ""
	}
	var env proto.Envelope
	var h proto.Hello
	if typ != websocket.MessageText || json.Unmarshal(data, &env) != nil || env.T != proto.THello || json.Unmarshal(data, &h) != nil {
		return nil, proto.ErrBadHello
	}
	if h.V != proto.TProtocol {
		return nil, proto.ErrVersion
	}
	if h.Token == "" {
		return nil, proto.ErrUnauthorized
	}
	roles := h.Roles[:0:0]
	for _, role := range h.Roles {
		if role == proto.RoleScreen || role == proto.RoleController {
			roles = append(roles, role)
		}
	}
	if len(roles) == 0 {
		return nil, proto.ErrBadHello
	}
	h.Roles = roles
	cctx, ccancel := context.WithTimeout(ctx, s.cfg.BackendTimeout)
	defer ccancel()
	id, err := s.checker.Check(cctx, h.Token)
	switch {
	case errors.Is(err, backend.ErrUnauthorized):
		return nil, proto.ErrUnauthorized
	case errors.Is(err, backend.ErrVoiceOff):
		return nil, proto.ErrVoiceOff
	case err != nil:
		s.log.Warn("backend check failed", "err", err)
		return nil, proto.ErrBackend
	}
	deviceID := id.DeviceID
	if deviceID == "" {
		b := make([]byte, randomIDBytes)
		_, _ = rand.Read(b)
		deviceID = "dev-" + hex.EncodeToString(b)
	}
	name := truncate(firstNonEmpty(h.Name, id.DeviceName, h.Client, "Device"), maxNameRunes)
	h.Client = truncate(h.Client, maxClientRunes)
	sess := session.NewSession(h, id, deviceID, name, c)
	if code := s.hub.Join(sess); code != "" {
		return nil, code
	}
	return sess, ""
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

func truncate(s string, max int) string {
	r := []rune(s)
	if len(r) > max {
		return string(r[:max])
	}
	return s
}

func (s *Server) readLoop(ctx context.Context, ws *websocket.Conn, c *conn, sess *session.Session) {
	idle := time.AfterFunc(s.cfg.IdleTimeout, func() { c.Close(proto.ErrIdleTimeout, "no frame for too long") })
	defer idle.Stop()
	for {
		typ, data, err := ws.Read(ctx)
		at := time.Now()
		if err != nil {
			return
		}
		idle.Reset(s.cfg.IdleTimeout)
		if typ == websocket.MessageBinary {
			s.hub.HandleBinary(sess, data)
			continue
		}
		var env proto.Envelope
		if json.Unmarshal(data, &env) != nil || env.T == "" {
			continue
		}
		s.hub.Handle(sess, env.T, data, at)
	}
}

// recheck asks the backend again twice per cache window, so a revoked device or a switched-off voice setting is
// out within one window. An unreachable backend keeps the socket (player tools still work).
func (s *Server) recheck(ctx context.Context, sess *session.Session) {
	t := time.NewTicker(s.cfg.AuthCache / 2)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
		cctx, cancel := context.WithTimeout(ctx, s.cfg.BackendTimeout)
		_, err := s.checker.Check(cctx, sess.Token())
		cancel()
		switch {
		case errors.Is(err, backend.ErrUnauthorized):
			s.hub.Kick(sess, proto.ErrRevoked, "this device is no longer signed in")
			return
		case errors.Is(err, backend.ErrVoiceOff):
			s.hub.Kick(sess, proto.ErrVoiceOff, "voice was switched off for this device")
			return
		}
	}
}

func (s *Server) pinger(ctx context.Context, c *conn) {
	t := time.NewTicker(s.cfg.PingInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-t.C:
			c.Send(proto.New(proto.TPing).With("ts", now.UnixMilli()))
		}
	}
}
