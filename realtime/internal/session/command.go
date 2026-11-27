package session

import (
	"encoding/json"
	"strings"
	"time"

	"github.com/evrenesat/u-tubot/realtime/internal/intent"
	"github.com/evrenesat/u-tubot/realtime/internal/proto"
	"github.com/evrenesat/u-tubot/realtime/internal/stats"
)

// Outcome states carried by an outcome frame.
const (
	stateOK        = "ok"
	stateFailed    = "failed"
	stateRefused   = "refused"
	stateTimeout   = "timeout"
	stateExpired   = "expired"
	stateBusy      = "busy"
	stateCancelled = "cancelled"
	stateOffline   = "offline"
	stateNone      = "none"
	stateClarify   = "clarify"
)

// apiOutcome maps a state to the history route's outcome vocabulary.
func apiOutcome(state string) string {
	switch state {
	case stateOK:
		return proto.OutcomeOK
	case stateRefused, stateBusy:
		return proto.OutcomeRefused
	case stateCancelled:
		return proto.OutcomeCancelled
	case stateNone:
		return proto.OutcomeNone
	case stateClarify:
		return proto.OutcomeClarify
	}
	return proto.OutcomeFailed
}

type settle struct{ state, message string }

// request is one user command on its way to a screen.
type request struct {
	origin *Session
	sayID  string
	text   string
	kind   string
	tIn    time.Time
	pin    string
	dec    intent.Decision
}

type pending struct {
	request
	id           string
	tool         string
	args         map[string]any
	target       *Session
	expiresAt    time.Time
	tQueued      time.Time
	tSent        time.Time
	tAck         time.Time
	queueWait    time.Duration
	sent         bool
	received     bool
	confirmShown bool
	answered     bool
	ended        bool
	waiting      bool
	ackTimer     *time.Timer
	expiryTimer  *time.Timer
	doneTimer    *time.Timer
}

type askOption struct{ label, deviceID string }

type askState struct {
	id      string
	options []askOption
	req     request
	timer   *time.Timer
}

func (h *Hub) handleFocus(s *Session, raw []byte) {
	var f proto.Focus
	if json.Unmarshal(raw, &f) != nil {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	if u == nil || u.sessions[s.DeviceID] != s {
		return
	}
	if !s.Roles[proto.RoleScreen] {
		h.errorLocked(s, proto.ErrNotScreen, "only a screen reports focus")
		return
	}
	switch f.Screen {
	case "player", "browse", "menu", "search", "other":
	default:
		h.errorLocked(s, proto.ErrBadFrame, "unknown screen")
		return
	}
	switch f.View {
	case "summary", "answer", "cuts", "none":
	case "":
		f.View = "none"
	default:
		h.errorLocked(s, proto.ErrBadFrame, "unknown view")
		return
	}
	if f.Rate <= 0 {
		f.Rate = 1
	}
	if f.Seq != 0 && f.Seq < s.focusSeq {
		return
	}
	s.focusSeq = f.Seq
	previous := s.summary
	s.focus, s.focusRaw = &f, append(json.RawMessage(nil), raw...)
	now := time.Now()
	s.summary = focusSummary(&f)
	if s.summary != previous {
		s.focusChanged = now
		h.broadcastPeersLocked(u, s)
	}
}

// focusSummary is what other devices see change: not the position, which moves all the time.
func focusSummary(f *proto.Focus) string {
	id := ""
	if f.Video != nil {
		id = f.Video.ID
	}
	cut := false
	if f.Cut != nil {
		cut = f.Cut.Active
	}
	b, _ := json.Marshal([]any{f.Screen, id, f.Playing, cut, f.View})
	return string(b)
}

// PositionAt extrapolates the screen's position from its last report, as the plan describes.
func PositionAt(f *proto.Focus, reportedAt, now time.Time) float64 {
	pos := f.PositionS
	if f.Playing {
		pos += now.Sub(reportedAt).Seconds() * f.Rate
	}
	if f.Video != nil && f.Video.DurationS > 0 && pos > f.Video.DurationS {
		pos = f.Video.DurationS
	}
	return pos
}

func (h *Hub) handleSay(s *Session, m proto.Say, tIn time.Time) {
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	if u == nil || u.sessions[s.DeviceID] != s {
		return
	}
	if !s.Roles[proto.RoleController] {
		h.errorLocked(s, proto.ErrNotController, "only a controller can speak")
		return
	}
	text := strings.TrimSpace(m.Text)
	if text == "" {
		h.errorLocked(s, proto.ErrBadFrame, "empty text")
		return
	}
	if len([]rune(text)) > h.cfg.MaxTextChars {
		h.errorLocked(s, proto.ErrTooLong, "text too long")
		return
	}
	id := clip(m.ID, maxIDRunes)
	if id == "" {
		id = h.newID("s")
	}
	r := request{origin: s, sayID: id, text: text, kind: KindText, tIn: tIn, pin: m.Target}
	if !h.allowUtteranceLocked(u, tIn) {
		h.errorLocked(s, proto.ErrRateLimited, MsgRateLimited)
		h.failRequestLocked(u, r, stateRefused, MsgRateLimited)
		return
	}
	h.processLocked(u, r)
}

func (h *Hub) allowUtteranceLocked(u *user, now time.Time) bool {
	cutoff := now.Add(-time.Minute)
	kept := u.utterances[:0]
	for _, t := range u.utterances {
		if t.After(cutoff) {
			kept = append(kept, t)
		}
	}
	u.utterances = kept
	if len(u.utterances) >= h.cfg.UtterancesPerMin {
		return false
	}
	u.utterances = append(u.utterances, now)
	return true
}

// processLocked runs the words of a command: a pending question first, then the phrase matcher.
func (h *Hub) processLocked(u *user, r request) {
	if h.answerByWordsLocked(u, r) {
		return
	}
	var focus *proto.Focus
	if guess, _, _ := h.chooseTargetLocked(u, "", r.pin); guess != nil {
		focus = guess.focus
	}
	dec := h.understand(r.text, focus)
	r.dec = dec
	_, known := intent.Lookup(dec.Tool)
	switch {
	case dec.Tool == "" || !known:
		h.failRequestLocked(u, r, stateNone, MsgNotUnderstd)
		return
	case dec.Tool == intent.None:
		say := dec.Say
		if say == "" {
			say = MsgNotUnderstd
		}
		h.failRequestLocked(u, r, stateNone, clip(say, maxMessageRunes))
		return
	case dec.Tool == intent.Clarify:
		h.clarifyLocked(u, r)
		return
	case dec.Tool == intent.Cancel && h.cancelPendingLocked(u, r):
		return
	}
	h.dispatchRequestLocked(u, r)
}

// failRequestLocked ends a request that never became a command.
func (h *Hub) failRequestLocked(u *user, r request, state, message string) {
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", r.sayID).With("state", proto.HeardFailed).With("text", r.text).With("message", message))
	h.emitLocked(u, &r, "", r.dec.Tool, r.dec.Args, settle{state, message}, map[string]time.Duration{})
}

func (h *Hub) clarifyLocked(u *user, r request) {
	args, err := intent.Validate(r.dec, nil)
	if err != nil {
		h.failRequestLocked(u, r, stateNone, err.Error())
		return
	}
	options := r.dec.Options
	if len(options) > intent.MaxOptions {
		options = options[:intent.MaxOptions]
	}
	text, _ := args["text"].(string)
	h.sendAllLocked(u, proto.New(proto.TAsk).With("id", h.newID("q")).With("text", text).With("options", options).
		With("expires_ms", time.Now().Add(h.cfg.AskWindow).UnixMilli()))
	h.emitLocked(u, &r, "", intent.Clarify, args, settle{stateClarify, ""}, map[string]time.Duration{})
}

// cancelPendingLocked drops the user's open question or confirmation. It reports false when there is none, so the
// cancel is sent to the screen (which may stop the request it just started).
func (h *Hub) cancelPendingLocked(u *user, r request) bool {
	if u.ask != nil {
		h.dropAskLocked(u, "")
	} else if p := h.confirmingLocked(u); p != nil {
		p.answered = true
		p.target.conn.Send(proto.New(proto.TAnswer).With("id", p.id).With("option", "no"))
	} else {
		return false
	}
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", r.sayID).With("state", proto.HeardUnderstood).With("text", r.text).With("tool", intent.Cancel))
	h.emitLocked(u, &r, "", intent.Cancel, nil, settle{stateCancelled, MsgCancelled}, map[string]time.Duration{})
	return true
}

func (h *Hub) confirmingLocked(u *user) *pending {
	var best *pending
	for _, s := range u.sessions {
		if p := s.inflight; p != nil && p.confirmShown && !p.answered && (best == nil || p.tAck.After(best.tAck)) {
			best = p
		}
	}
	return best
}

// answerByWordsLocked reads a spoken answer to an open question or confirmation.
func (h *Hub) answerByWordsLocked(u *user, r request) bool {
	if u.ask != nil {
		labels := make([]string, len(u.ask.options))
		for i, o := range u.ask.options {
			labels[i] = o.label
		}
		if idx := intent.OptionIndex(r.text, labels); idx >= 0 {
			h.resolveAskLocked(u, idx)
			return true
		}
		if intent.Stage1(r.text).Tool == intent.Cancel {
			return h.cancelPendingLocked(u, r)
		}
		h.dropAskLocked(u, "")
	}
	if p := h.confirmingLocked(u); p != nil {
		if yn := intent.YesNo(r.text); yn != 0 {
			h.forwardAnswerLocked(p, yn > 0)
			h.sendAllLocked(u, proto.New(proto.THeard).With("id", r.sayID).With("state", proto.HeardUnderstood).With("text", r.text).With("tool", "answer"))
			return true
		}
	}
	return false
}

func (h *Hub) forwardAnswerLocked(p *pending, yes bool) {
	option := "no"
	if yes {
		option = "yes"
	}
	p.answered = true
	p.target.conn.Send(proto.New(proto.TAnswer).With("id", p.id).With("option", option))
	if p.doneTimer != nil {
		p.doneTimer.Stop()
	}
	p.doneTimer = time.AfterFunc(h.cfg.DoneTimeout, func() { h.onDoneTimeout(p) })
}

func (h *Hub) handleAnswer(s *Session, m proto.Answer) {
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	if u == nil || u.sessions[s.DeviceID] != s {
		return
	}
	if u.ask != nil && u.ask.id == m.ID {
		for i, o := range u.ask.options {
			if strings.EqualFold(o.label, m.Option) || o.deviceID == m.Option {
				h.resolveAskLocked(u, i)
				return
			}
		}
		return
	}
	for _, screen := range u.sessions {
		p := screen.inflight
		if p == nil || p.id != m.ID || !p.confirmShown || p.answered || screen == s {
			continue
		}
		switch strings.ToLower(m.Option) {
		case "yes", "ok":
			h.forwardAnswerLocked(p, true)
		case "no", "back":
			h.forwardAnswerLocked(p, false)
		}
		return
	}
}

// chooseTargetLocked picks the screen for a command (plan 2.3, "Target"). An empty tool means no tool filter.
// It returns a screen, or a list of options to ask about, or a message for the user.
func (h *Hub) chooseTargetLocked(u *user, tool, pin string) (*Session, []askOption, string) {
	var screens []*Session
	for _, s := range u.sessions {
		if s.Roles[proto.RoleScreen] {
			screens = append(screens, s)
		}
	}
	if pin != "" {
		s := u.sessions[pin]
		if s == nil || !s.Roles[proto.RoleScreen] {
			return nil, nil, MsgScreenGone
		}
		if tool != "" && !s.Tools[tool] {
			return nil, nil, s.Name + " cannot do that"
		}
		return s, nil, ""
	}
	if len(screens) == 0 {
		return nil, nil, MsgNoScreen
	}
	candidates := screens[:0:0]
	for _, s := range screens {
		if tool == "" || s.Tools[tool] {
			candidates = append(candidates, s)
		}
	}
	switch len(candidates) {
	case 0:
		if len(screens) == 1 {
			return nil, nil, screens[0].Name + " cannot do that"
		}
		return nil, nil, "None of the screens can do that"
	case 1:
		return candidates[0], nil, ""
	}
	var playing []*Session
	for _, s := range candidates {
		if s.focus != nil && s.focus.Playing {
			playing = append(playing, s)
		}
	}
	if len(playing) == 1 {
		return playing[0], nil, ""
	}
	if len(playing) == 0 {
		var recent *Session
		cutoff := time.Now().Add(-h.cfg.RecentFocus)
		for _, s := range candidates {
			if s.focus != nil && s.focusChanged.After(cutoff) && (recent == nil || s.focusChanged.After(recent.focusChanged)) {
				recent = s
			}
		}
		if recent != nil {
			return recent, nil, ""
		}
		playing = candidates
	}
	return nil, askOptions(playing), ""
}

func askOptions(screens []*Session) []askOption {
	names := map[string]int{}
	for _, s := range screens {
		names[strings.ToLower(s.Name)]++
	}
	options := make([]askOption, 0, len(screens))
	for _, s := range screens {
		label := s.Name
		if names[strings.ToLower(s.Name)] > 1 {
			label += " (" + shortID(s.DeviceID) + ")"
		}
		options = append(options, askOption{label: label, deviceID: s.DeviceID})
	}
	return options
}

func shortID(id string) string {
	if len(id) > 4 {
		return id[len(id)-4:]
	}
	return id
}

// dispatchRequestLocked picks the target, validates and queues the command.
func (h *Hub) dispatchRequestLocked(u *user, r request) {
	target, options, message := h.chooseTargetLocked(u, r.dec.Tool, r.pin)
	switch {
	case message != "":
		state := stateRefused
		if message == MsgNoScreen || message == MsgScreenGone {
			state = stateOffline
		}
		h.failRequestLocked(u, r, state, message)
		return
	case target == nil:
		h.askTargetLocked(u, r, options)
		return
	}
	args, err := intent.Validate(r.dec, target.focus)
	if err != nil {
		h.failRequestLocked(u, r, stateRefused, err.Error())
		return
	}
	h.sendAllLocked(u, proto.New(proto.THeard).With("id", r.sayID).With("state", proto.HeardUnderstood).With("text", r.text).With("tool", r.dec.Tool))
	now := time.Now()
	p := &pending{request: r, id: h.newID("c"), tool: r.dec.Tool, args: args, target: target, expiresAt: now.Add(h.cfg.CommandExpiry)}
	h.enqueueLocked(u, p)
}

func (h *Hub) askTargetLocked(u *user, r request, options []askOption) {
	if u.ask != nil {
		h.dropAskLocked(u, "")
	}
	labels := make([]string, len(options))
	for i, o := range options {
		labels[i] = o.label
	}
	ask := &askState{id: h.newID("q"), options: options, req: r}
	ask.timer = time.AfterFunc(h.cfg.AskWindow, func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		if uu := h.users[r.origin.User]; uu != nil && uu.ask == ask {
			h.dropAskLocked(uu, MsgNoAnswerAsk)
		}
	})
	u.ask = ask
	h.sendAllLocked(u, proto.New(proto.TAsk).With("id", ask.id).With("text", strings.Join(labels, " or ")+"?").
		With("options", labels).With("expires_ms", time.Now().Add(h.cfg.AskWindow).UnixMilli()))
}

func (h *Hub) resolveAskLocked(u *user, idx int) {
	ask := u.ask
	ask.timer.Stop()
	u.ask = nil
	r := ask.req
	r.pin = ask.options[idx].deviceID
	r.tIn = time.Now()
	h.dispatchRequestLocked(u, r)
}

func (h *Hub) dropAskLocked(u *user, message string) {
	ask := u.ask
	if ask == nil {
		return
	}
	ask.timer.Stop()
	u.ask = nil
	h.emitLocked(u, &ask.req, "", ask.req.dec.Tool, ask.req.dec.Args, settle{stateCancelled, message}, map[string]time.Duration{})
}

// enqueueLocked sends the command now, or queues it behind the one the screen is handling.
func (h *Hub) enqueueLocked(u *user, p *pending) {
	t := p.target
	switch {
	case t.inflight == nil:
		h.sendLocked(u, p)
	case len(t.waiting) < h.cfg.MaxWaiting:
		p.waiting, p.tQueued = true, time.Now()
		t.waiting = append(t.waiting, p)
		p.expiryTimer = time.AfterFunc(h.cfg.CommandExpiry, func() { h.onExpire(p) })
	default:
		h.finishLocked(u, p, settle{stateBusy, MsgBusy})
	}
}

func (h *Hub) sendLocked(u *user, p *pending) {
	t := p.target
	now := time.Now()
	if !now.Before(p.expiresAt) {
		h.finishLocked(u, p, settle{stateExpired, MsgExpired})
		return
	}
	if p.expiryTimer != nil {
		p.expiryTimer.Stop()
	}
	p.waiting = false
	t.inflight = p
	p.sent, p.tSent = true, now
	if !p.tQueued.IsZero() {
		p.queueWait = now.Sub(p.tQueued)
	}
	frame := proto.New(proto.TCommand).With("id", p.id).With("tool", p.tool).With("args", p.args).
		With("origin", map[string]any{"device_id": p.origin.DeviceID, "kind": p.kind}).
		With("expires_ms", p.expiresAt.UnixMilli())
	if text, eta, need := intent.Confirm(p.tool, p.args, t.focus); need {
		confirm := map[string]any{"text": text}
		if eta > 0 {
			confirm["eta_s"] = eta
		}
		frame.With("confirm", confirm)
	} else {
		frame.With("confirm", nil)
	}
	if !t.conn.Send(frame) {
		h.finishLocked(u, p, settle{stateFailed, MsgNoAnswer})
		t.conn.Close(proto.ErrBusy, "too slow")
		return
	}
	p.ackTimer = time.AfterFunc(h.cfg.AckTimeout, func() { h.onAckTimeout(p) })
}

func (h *Hub) onAckTimeout(p *pending) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if p.ended || p.received {
		return
	}
	u := h.users[p.origin.User]
	if u == nil {
		return
	}
	p.target.conn.Send(proto.New(proto.TRevoke).With("id", p.id).With("reason", stateTimeout))
	h.finishLocked(u, p, settle{stateTimeout, MsgNoAnswer})
}

func (h *Hub) onDoneTimeout(p *pending) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if p.ended {
		return
	}
	u := h.users[p.origin.User]
	if u == nil {
		return
	}
	p.target.conn.Send(proto.New(proto.TRevoke).With("id", p.id).With("reason", stateTimeout))
	if p.confirmShown && !p.answered {
		h.finishLocked(u, p, settle{stateCancelled, MsgNoAnswerAsk})
		return
	}
	h.finishLocked(u, p, settle{stateTimeout, MsgNotFinished})
}

func (h *Hub) onExpire(p *pending) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if p.ended || !p.waiting {
		return
	}
	if u := h.users[p.origin.User]; u != nil {
		h.finishLocked(u, p, settle{stateExpired, MsgExpired})
	}
}

func (h *Hub) handleAck(s *Session, a proto.Ack) {
	now := time.Now()
	h.mu.Lock()
	defer h.mu.Unlock()
	u := h.users[s.User]
	p := s.inflight
	if u == nil || u.sessions[s.DeviceID] != s || p == nil || p.id != a.ID || p.ended {
		return
	}
	if !p.received {
		p.received, p.tAck = true, now
		if p.ackTimer != nil {
			p.ackTimer.Stop()
		}
		p.doneTimer = time.AfterFunc(h.cfg.DoneTimeout, func() { h.onDoneTimeout(p) })
	}
	message := clip(a.Message, maxMessageRunes)
	switch a.State {
	case proto.AckReceived:
	case proto.AckConfirmShown:
		if !p.confirmShown {
			p.confirmShown = true
			p.tAck = now
			p.doneTimer.Stop()
			p.doneTimer = time.AfterFunc(h.cfg.ConfirmWindow, func() { h.onDoneTimeout(p) })
		}
	case proto.AckStarted, proto.AckDone:
		h.finishLocked(u, p, settle{stateOK, message})
	case proto.AckFailed:
		if message == "" {
			message = "That did not work"
		}
		h.finishLocked(u, p, settle{stateFailed, message})
	case proto.AckRefused:
		if message == "" {
			message = "That is not possible now"
		}
		h.finishLocked(u, p, settle{stateRefused, message})
	}
}

// finishLocked ends a command, frees its screen's slot and starts the next waiting command.
func (h *Hub) finishLocked(u *user, p *pending, st settle) {
	if p.ended {
		return
	}
	p.ended = true
	for _, t := range []*time.Timer{p.ackTimer, p.expiryTimer, p.doneTimer} {
		if t != nil {
			t.Stop()
		}
	}
	t := p.target
	freed := false
	if t.inflight == p {
		t.inflight, freed = nil, true
	} else {
		for i, w := range t.waiting {
			if w == p {
				t.waiting = append(t.waiting[:i:i], t.waiting[i+1:]...)
				break
			}
		}
	}
	now := time.Now()
	hops := map[string]time.Duration{}
	if p.sent {
		hops[stats.HopServer] = p.tSent.Sub(p.tIn) - p.queueWait
		hops[stats.HopQueue] = p.queueWait
	}
	if p.received {
		hops[stats.HopPush] = p.tAck.Sub(p.tSent)
		hops[stats.HopAct] = now.Sub(p.tAck)
	}
	h.emitLocked(u, &p.request, p.id, p.tool, p.args, st, hops)
	if freed && u.sessions[t.DeviceID] == t {
		h.startNextLocked(u, t)
	}
}

func (h *Hub) startNextLocked(u *user, t *Session) {
	for t.inflight == nil && len(t.waiting) > 0 {
		next := t.waiting[0]
		t.waiting = t.waiting[1:]
		h.sendLocked(u, next)
	}
}

// emitLocked tells the user's devices how a request ended, updates the statistics and files the history record.
func (h *Hub) emitLocked(u *user, r *request, commandID, tool string, args map[string]any, st settle, hops map[string]time.Duration) {
	if st.message != "" && st.state != stateOK {
		h.sendAllLocked(u, proto.New(proto.TReply).With("id", r.sayID).With("text", st.message).With("more", false).With("speak", false))
	}
	frame := proto.New(proto.TOutcome).With("id", r.sayID).With("tool", tool).With("state", st.state)
	if commandID != "" {
		frame.With("command_id", commandID)
	}
	if st.message != "" {
		frame.With("message", st.message)
	}
	h.sendAllLocked(u, frame)
	if hops == nil {
		hops = map[string]time.Duration{}
	}
	hops[stats.HopTotal] = time.Since(r.tIn)
	h.stats.Add(stats.Record{Tool: tool, Family: intent.Family(tool), Outcome: apiOutcome(st.state), Hops: hops})
	h.record(r.origin, r.text, tool, args, apiOutcome(st.state), hops)
}
