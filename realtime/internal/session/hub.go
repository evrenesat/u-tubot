// Package session holds the live server's state: connected devices, the focus store, target choice, commands with
// their acknowledgements and expiry, confirmations and questions, limits and the marks behind the statistics.
//
// All state sits behind one mutex. Every operation under it takes microseconds and only writes into bounded queues
// (Conn.Send never blocks), so a slow device cannot hold up another one.
package session

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/evrenesat/u-tubot/realtime/internal/backend"
	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/intent"
	"github.com/evrenesat/u-tubot/realtime/internal/proto"
	"github.com/evrenesat/u-tubot/realtime/internal/stats"
)

const (
	recordTimeout   = 5 * time.Second
	maxNameRunes    = 64
	maxIDRunes      = 64
	maxMessageRunes = 300
	// KindVoice and KindText name where a command's words came from.
	KindText = "text"
)

// Messages shown to the user (plan 2.14).
const (
	MsgNoScreen     = "The TV is not connected"
	MsgNoAnswer     = "The TV did not answer"
	MsgNotUnderstd  = "I did not understand that"
	MsgBusy         = "The TV is busy, try again"
	MsgExpired      = "That command expired"
	MsgDisconnected = "The TV disconnected"
	MsgNoSpeech     = "Speech is not available on this server"
	MsgRateLimited  = "Too many commands, wait a moment"
	MsgDailyAudio   = "Today's voice time is used up"
	MsgTooLong      = "That recording was too long"
	MsgNoAnswerAsk  = "No answer, cancelled"
	MsgCancelled    = "Cancelled"
	MsgNotFinished  = "The TV did not finish"
	MsgScreenGone   = "That screen is not connected"
	MsgListenEnded  = "Listening ended"
)

// Conn is a device's connection as the hub sees it.
type Conn interface {
	// Send queues a frame and never blocks. It reports false when the frame could not be queued.
	Send(v any) bool
	// Close sends an error frame with the code and ends the connection.
	Close(code, message string)
}

// Understander turns the words of a command into a decision. The focus is the one of the screen the command would
// most likely go to (nil when there is none). It runs under the hub's lock, so it must answer in microseconds: the
// phrase matcher does; a model stage (checkpoint 4) has to run before the lock is taken.
type Understander func(text string, focus *proto.Focus) intent.Decision

// Stage1Only is the checkpoint 2 understanding: the phrase matcher, no model.
func Stage1Only(text string, _ *proto.Focus) intent.Decision { return intent.Stage1(text) }

// Options configure a hub.
type Options struct {
	Config     config.Config
	Recorder   backend.Recorder
	Stats      *stats.Store
	Understand Understander
	Log        *slog.Logger
}

// Hub is the whole live state.
type Hub struct {
	cfg        config.Config
	rec        backend.Recorder
	stats      *stats.Store
	understand Understander
	log        *slog.Logger

	mu      sync.Mutex
	users   map[string]*user
	limits  map[string]*limiter
	seq     uint64
	closing bool

	recMu   sync.Mutex
	recN    int
	recDone *sync.Cond
	recQ    chan recJob
	quit    chan struct{}
	quitOne sync.Once
}

type recJob struct {
	token string
	rec   backend.Record
}

type user struct {
	name     string
	sessions map[string]*Session
	ask      *askState
}

// limiter is a user's rate state. It lives apart from the connected user so that reconnecting does not reset it, and
// is evicted once it has been quiet for a day.
type limiter struct {
	utterances []time.Time
	audioDay   string
	audioSecs  float64
	sayIDs     map[string]time.Time
	touched    time.Time
}

const limiterIdle = 26 * time.Hour
const maxRememberedSayIDs = 512

// maxFocusRelayBytes bounds the focus frame relayed to other devices in welcome and peers.
const maxFocusRelayBytes = 8 * 1024

// Session is one connected device.
type Session struct {
	DeviceID string
	User     string
	Name     string
	Client   string
	Roles    map[string]bool
	Tools    map[string]bool
	Mic      bool
	Speaker  bool
	Identity backend.Identity

	token string
	conn  Conn

	// Guarded by the hub's mutex.
	focus        *proto.Focus
	focusRaw     json.RawMessage
	focusSeq     int64
	focusAt      time.Time
	focusChanged time.Time
	summary      string
	inflight     *pending
	waiting      []*pending
	listen       *listenState
	clockOffset  int64
}

// Token is the device's bearer token, kept in memory for the periodic re-check and the history record.
func (s *Session) Token() string { return s.token }

// NewSession describes a device that passed the hello check.
func NewSession(h proto.Hello, id backend.Identity, deviceID, name string, conn Conn) *Session {
	s := &Session{
		DeviceID: deviceID, User: id.User, Name: name, Client: h.Client, Mic: h.Mic, Speaker: h.Speaker,
		Identity: id, token: h.Token, conn: conn, Roles: map[string]bool{}, Tools: map[string]bool{},
	}
	for _, r := range h.Roles {
		s.Roles[r] = true
	}
	for _, t := range h.Tools {
		if _, ok := intent.Lookup(t); ok {
			s.Tools[t] = true
		}
	}
	return s
}

// New builds a hub.
func New(o Options) *Hub {
	h := &Hub{cfg: o.Config, rec: o.Recorder, stats: o.Stats, understand: o.Understand, log: o.Log, users: map[string]*user{}, limits: map[string]*limiter{}, quit: make(chan struct{})}
	h.recDone = sync.NewCond(&h.recMu)
	h.recQ = make(chan recJob, h.cfg.RecordQueue)
	for i := 0; i < h.cfg.RecordWorkers; i++ {
		go h.recordWorker()
	}
	if h.understand == nil {
		h.understand = Stage1Only
	}
	if h.log == nil {
		h.log = slog.New(slog.NewTextHandler(discard{}, nil))
	}
	if h.stats == nil {
		h.stats = stats.New(config.DefaultStatsWindow)
	}
	return h
}

type discard struct{}

func (discard) Write(p []byte) (int, error) { return len(p), nil }

// Stats returns the statistics store.
func (h *Hub) Stats() *stats.Store { return h.stats }

// Wait blocks until the background history records are filed (tests and shutdown).
func (h *Hub) Wait() {
	h.recMu.Lock()
	defer h.recMu.Unlock()
	for h.recN > 0 {
		h.recDone.Wait()
	}
}

// Connections counts the connected devices.
func (h *Hub) Connections() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	n := 0
	for _, u := range h.users {
		n += len(u.sessions)
	}
	return n
}

// Join registers a session after its hello passed. It sends the welcome frame first, tells the user's other
// devices, and refuses with proto.ErrTooMany when the user holds too many sockets. A second socket of the same
// device replaces the older one.
func (h *Hub) Join(s *Session) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closing {
		return proto.ErrServerShutdown
	}
	h.sweepLimitsLocked(time.Now())
	u := h.users[s.User]
	if u == nil {
		u = &user{name: s.User, sessions: map[string]*Session{}}
		h.users[s.User] = u
	}
	if old := u.sessions[s.DeviceID]; old != nil {
		h.removeLocked(u, old, MsgDisconnected)
		old.conn.Close(proto.ErrReplaced, "this device connected again")
	}
	if len(u.sessions) >= h.cfg.MaxConnsPerUser {
		return proto.ErrTooMany
	}
	welcome := proto.New(proto.TWelcome).
		With("device_id", s.DeviceID).With("user", s.User).
		With("voice", map[string]any{
			"enabled": s.Identity.VoiceOn, "listen_mode": s.Identity.ListenMode, "speak": s.Identity.Speak,
			"retention_days": s.Identity.RetentionDays,
		}).
		With("peers", h.peersLocked(u, s)).With("server_time_ms", time.Now().UnixMilli())
	s.conn.Send(welcome)
	u.sessions[s.DeviceID] = s
	h.broadcastPeersLocked(u, s)
	return ""
}

// Leave removes a session. Its commands end as failed; nothing is replayed after a reconnect.
func (h *Hub) Leave(s *Session) {
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	if u == nil || u.sessions[s.DeviceID] != s {
		return
	}
	h.removeLocked(u, s, MsgDisconnected)
	if len(u.sessions) == 0 {
		delete(h.users, u.name)
	}
}

// Kick closes a session with a code (revoked token, voice switched off).
func (h *Hub) Kick(s *Session, code, message string) {
	s.conn.Close(code, message)
}

// CloseAll ends every connection (shutdown).
func (h *Hub) CloseAll(code, message string) {
	h.mu.Lock()
	h.closing = true
	var all []*Session
	for _, u := range h.users {
		for _, s := range u.sessions {
			all = append(all, s)
		}
	}
	h.mu.Unlock()
	for _, s := range all {
		s.conn.Close(code, message)
	}
}

func (h *Hub) removeLocked(u *user, s *Session, why string) {
	delete(u.sessions, s.DeviceID)
	h.endListenLocked(u, s, MsgListenEnded)
	for _, p := range append(append([]*pending(nil), s.inflight), s.waiting...) {
		if p != nil {
			h.finishLocked(u, p, settle{state: stateFailed, message: why})
		}
	}
	s.inflight, s.waiting = nil, nil
	if u.ask != nil {
		for _, o := range u.ask.options {
			if o.deviceID == s.DeviceID {
				h.dropAskLocked(u, MsgScreenGone)
				break
			}
		}
	}
	h.broadcastPeersLocked(u, s)
}

func (h *Hub) peersLocked(u *user, except *Session) []proto.Peer {
	peers := []proto.Peer{}
	for _, p := range u.sessions {
		if p == except {
			continue
		}
		peer := proto.Peer{DeviceID: p.DeviceID, Name: p.Name, Client: p.Client, Roles: roleList(p)}
		if p.Roles[proto.RoleScreen] && p.focusRaw != nil {
			peer.Focus = p.focusRaw
		}
		peers = append(peers, peer)
	}
	return peers
}

func roleList(s *Session) []string {
	roles := []string{}
	for _, r := range []string{proto.RoleScreen, proto.RoleController} {
		if s.Roles[r] {
			roles = append(roles, r)
		}
	}
	return roles
}

func (h *Hub) broadcastPeersLocked(u *user, except *Session) {
	for _, s := range u.sessions {
		if s == except {
			continue
		}
		s.conn.Send(proto.New(proto.TPeers).With("peers", h.peersLocked(u, s)))
	}
}

func (h *Hub) sendAllLocked(u *user, frame proto.Out) {
	for _, s := range u.sessions {
		s.conn.Send(frame)
	}
}

func (h *Hub) errorLocked(s *Session, code, message string) {
	s.conn.Send(proto.New(proto.TError).With("code", code).With("message", message))
}

func (h *Hub) newID(prefix string) string {
	h.seq++
	return fmt.Sprintf("%s%d", prefix, h.seq)
}

func clip(s string, max int) string {
	r := []rune(strings.TrimSpace(s))
	if len(r) > max {
		r = r[:max]
	}
	return string(r)
}

// Handle processes one text frame of a registered session. at is when the frame came off the socket: the mark t1 of
// the plan, so the server's own time includes decoding.
func (h *Hub) Handle(s *Session, t string, raw []byte, at time.Time) {
	switch t {
	case proto.TFocus:
		h.handleFocus(s, raw)
	case proto.TSay:
		var m proto.Say
		if json.Unmarshal(raw, &m) == nil {
			h.handleSay(s, m, at)
		}
	case proto.TListen:
		var m proto.Listen
		if json.Unmarshal(raw, &m) == nil {
			h.handleListen(s, m)
		}
	case proto.TAck:
		var m proto.Ack
		if json.Unmarshal(raw, &m) == nil {
			h.handleAck(s, m)
		}
	case proto.TAnswer:
		var m proto.Answer
		if json.Unmarshal(raw, &m) == nil {
			h.handleAnswer(s, m)
		}
	case proto.TPing:
		var m proto.Ping
		_ = json.Unmarshal(raw, &m)
		s.conn.Send(proto.New(proto.TPong).With("ts", m.TS).With("server_ms", time.Now().UnixMilli()))
	case proto.TPong:
		var m proto.Ping
		if json.Unmarshal(raw, &m) == nil && m.TS > 0 {
			h.mu.Lock()
			s.clockOffset = m.TS - time.Now().UnixMilli()
			h.mu.Unlock()
		}
	}
}

// ClockOffsetMs is the client's clock minus the server's, from the last pong.
func (h *Hub) ClockOffsetMs(s *Session) int64 {
	h.mu.Lock()
	defer h.mu.Unlock()
	return s.clockOffset
}

func (h *Hub) record(origin *Session, text, tool string, args map[string]any, outcome string, hops map[string]time.Duration) {
	if h.rec == nil || origin == nil {
		return
	}
	marks := map[string]int{}
	for hop, d := range hops {
		marks[hop+"_ms"] = int(d.Milliseconds())
	}
	rec := backend.Record{Text: text, Tool: tool, Args: args, Outcome: outcome, Marks: marks}
	if rec.Args == nil {
		rec.Args = map[string]any{}
	}
	h.recMu.Lock()
	h.recN++
	h.recMu.Unlock()
	select {
	case h.recQ <- recJob{token: origin.token, rec: rec}:
	default:
		h.recordDone()
		h.log.Warn("history queue full, record dropped")
	}
}

func (h *Hub) recordDone() {
	h.recMu.Lock()
	h.recN--
	h.recDone.Broadcast()
	h.recMu.Unlock()
}

func (h *Hub) recordWorker() {
	for {
		select {
		case <-h.quit:
			return
		case job := <-h.recQ:
			ctx, cancel := context.WithTimeout(context.Background(), recordTimeout)
			if err := h.rec.Record(ctx, job.token, job.rec); err != nil {
				h.log.Warn("history record failed", "err", err)
			}
			cancel()
			h.recordDone()
		}
	}
}

// Close stops the history workers. Call Wait first to let queued records go out.
func (h *Hub) Close() { h.quitOne.Do(func() { close(h.quit) }) }

func (h *Hub) limiterLocked(name string, now time.Time) *limiter {
	l := h.limits[name]
	if l == nil {
		l = &limiter{sayIDs: map[string]time.Time{}}
		h.limits[name] = l
	}
	l.touched = now
	return l
}

func (h *Hub) sweepLimitsLocked(now time.Time) {
	for name, l := range h.limits {
		if _, online := h.users[name]; !online && now.Sub(l.touched) > limiterIdle {
			delete(h.limits, name)
		}
	}
}
