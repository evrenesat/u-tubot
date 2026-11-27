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
		s.listen = nil
		secs := now.Sub(l.started).Seconds()
		if secs > float64(h.cfg.MaxUtteranceSecs) {
			h.failListenLocked(u, l, MsgTooLong)
			return
		}
		h.addAudioLocked(u, secs, now)
		// Checkpoint 2 has no speech engine: the audio is dropped here, never stored, and the user is told so.
		h.failListenLocked(u, l, MsgNoSpeech)
	case proto.ListenCancel:
		if l := s.listen; l != nil && l.id == id {
			s.listen = nil
			h.sendAllLocked(u, proto.New(proto.THeard).With("id", l.id).With("state", proto.HeardFailed).With("message", MsgCancelled))
		}
	}
}

func (h *Hub) startListenLocked(u *user, s *Session, id string, m proto.Listen, now time.Time) {
	if id == "" {
		id = h.newID("l")
	}
	if l := s.listen; l != nil && now.Sub(l.started) < time.Duration(h.cfg.MaxUtteranceSecs)*time.Second {
		h.errorLocked(s, proto.ErrBusy, "one utterance at a time")
		return
	}
	if h.audioTodayLocked(u, now) >= float64(h.cfg.AudioSecondsPerDay) {
		h.errorLocked(s, proto.ErrDailyAudio, MsgDailyAudio)
		h.sendAllLocked(u, proto.New(proto.THeard).With("id", id).With("state", proto.HeardFailed).With("message", MsgDailyAudio))
		return
	}
	if !h.allowUtteranceLocked(u, now) {
		h.errorLocked(s, proto.ErrRateLimited, MsgRateLimited)
		h.sendAllLocked(u, proto.New(proto.THeard).With("id", id).With("state", proto.HeardFailed).With("message", MsgRateLimited))
		return
	}
	s.listen = &listenState{id: id, format: m.Format, started: now, pin: m.Target}
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", id).With("state", proto.HeardListening))
}

func (h *Hub) failListenLocked(u *user, l *listenState, message string) {
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", l.id).With("state", proto.HeardFailed).With("message", message))
	h.sendAllLocked(u, proto.New(proto.TReply).With("id", l.id).With("text", message).With("more", false).With("speak", false))
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
		s.listen = nil
		h.errorLocked(s, proto.ErrTooLong, MsgTooLong)
		h.failListenLocked(u, l, MsgTooLong)
	}
}

func dayKey(t time.Time) string { return t.UTC().Format("2006-01-02") }

func (h *Hub) audioTodayLocked(u *user, now time.Time) float64 {
	if u.audioDay != dayKey(now) {
		u.audioDay, u.audioSecs = dayKey(now), 0
	}
	return u.audioSecs
}

func (h *Hub) addAudioLocked(u *user, secs float64, now time.Time) {
	h.audioTodayLocked(u, now)
	u.audioSecs += secs
}
