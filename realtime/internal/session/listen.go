package session

import (
	"time"

	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

type listenState struct {
	id      string
	format  string
	started time.Time
	bytes   int
	pin     string
	timer   *time.Timer
}

func (h *Hub) handleListen(s *Session, m proto.Listen) {
	now := time.Now()
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	if u == nil || u.sessions[s.DeviceID] != s {
		return
	}
	if !s.Roles[proto.RoleController] {
		h.errorLocked(s, proto.ErrNotController, "only a controller can listen")
		return
	}
	id := clip(m.ID, maxIDRunes)
	switch m.State {
	case proto.ListenStart:
		h.startListenLocked(u, s, id, m, now)
	case proto.ListenEnd:
		l := s.listen
		if l == nil || l.id != id {
			h.errorLocked(s, proto.ErrNoListen, "no utterance is open")
			return
		}
		// Checkpoint 2 has no speech engine: the audio is dropped, never stored, and the user is told so.
		h.finishListenLocked(u, s, MsgNoSpeech)
	case proto.ListenCancel:
		if l := s.listen; l != nil && l.id == id {
			h.finishListenLocked(u, s, MsgCancelled)
		}
	}
}

func (h *Hub) startListenLocked(u *user, s *Session, id string, m proto.Listen, now time.Time) {
	if id == "" {
		id = h.newID("l")
	}
	if s.listen != nil {
		h.errorLocked(s, proto.ErrBusy, "one utterance at a time")
		return
	}
	lim := h.limiterLocked(u.name, now)
	if h.audioTodayLocked(lim, now) >= float64(h.cfg.AudioSecondsPerDay) {
		h.errorLocked(s, proto.ErrDailyAudio, MsgDailyAudio)
		h.sendAllLocked(u, proto.New(proto.THeard).With("id", id).With("state", proto.HeardFailed).With("message", MsgDailyAudio))
		return
	}
	if !h.allowUtteranceLocked(u.name, now) {
		h.errorLocked(s, proto.ErrRateLimited, MsgRateLimited)
		h.sendAllLocked(u, proto.New(proto.THeard).With("id", id).With("state", proto.HeardFailed).With("message", MsgRateLimited))
		return
	}
	l := &listenState{id: id, format: m.Format, started: now, pin: m.Target}
	// A recording that is never ended must not hold the microphone indicator or the day's budget: it ends itself.
	l.timer = time.AfterFunc(time.Duration(h.cfg.MaxUtteranceSecs)*time.Second, func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		if uu := h.users[s.User]; uu != nil && s.listen == l {
			h.errorLocked(s, proto.ErrTooLong, MsgTooLong)
			h.finishListenLocked(uu, s, MsgTooLong)
		}
	})
	s.listen = l
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", id).With("state", proto.HeardListening))
}

// endListenLocked closes an open utterance on every exit path: the elapsed time (at most the utterance limit) is
// charged to the day's budget and the user's devices are told it failed, so no screen keeps a microphone indicator on.
func (h *Hub) endListenLocked(u *user, s *Session, message string) {
	l := s.listen
	if l == nil {
		return
	}
	s.listen = nil
	if l.timer != nil {
		l.timer.Stop()
	}
	now := time.Now()
	secs := now.Sub(l.started).Seconds()
	if max := float64(h.cfg.MaxUtteranceSecs); secs > max {
		secs = max
	}
	lim := h.limiterLocked(u.name, now)
	h.audioTodayLocked(lim, now)
	lim.audioSecs += secs
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", l.id).With("state", proto.HeardFailed).With("message", message))
}

// finishListenLocked is endListenLocked plus a reply the user can read.
func (h *Hub) finishListenLocked(u *user, s *Session, message string) {
	l := s.listen
	if l == nil {
		return
	}
	h.endListenLocked(u, s, message)
	if message != MsgCancelled {
		h.sendAllLocked(u, proto.New(proto.TReply).With("id", l.id).With("text", message).With("more", false).With("speak", false))
	}
}

// HandleBinary takes an audio frame of the open utterance. The bytes are counted and dropped: this checkpoint has
// no speech engine, and the live server never writes audio anywhere.
func (h *Hub) HandleBinary(s *Session, data []byte) {
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	if u == nil || u.sessions[s.DeviceID] != s {
		return
	}
	l := s.listen
	if l == nil {
		h.errorLocked(s, proto.ErrNoListen, "no utterance is open")
		return
	}
	l.bytes += len(data)
	if l.bytes > h.cfg.MaxUtteranceBytes {
		h.errorLocked(s, proto.ErrTooLong, MsgTooLong)
		h.finishListenLocked(u, s, MsgTooLong)
	}
}

func dayKey(t time.Time) string { return t.UTC().Format("2006-01-02") }

func (h *Hub) audioTodayLocked(l *limiter, now time.Time) float64 {
	if l.audioDay != dayKey(now) {
		l.audioDay, l.audioSecs = dayKey(now), 0
	}
	return l.audioSecs
}
