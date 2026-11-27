// Package proto holds the frames of the live server's control channel (ai/CONTRACT.md, "Live server").
package proto

import "encoding/json"

// Frame types. Unknown types and fields are ignored by every side.
const (
	THello    = "hello"
	TFocus    = "focus"
	TListen   = "listen"
	TSay      = "say"
	TAck      = "ack"
	TAnswer   = "answer"
	TPing     = "ping"
	TPong     = "pong"
	TWelcome  = "welcome"
	TError    = "error"
	THeard    = "heard"
	TCommand  = "command"
	TReply    = "reply"
	TAsk      = "ask"
	TOutcome  = "outcome"
	TPeers    = "peers"
	TRevoke   = "revoke"
	TProtocol = 1
)

// Roles of a device.
const (
	RoleScreen     = "screen"
	RoleController = "controller"
)

// Error codes carried by an error frame.
const (
	ErrUnauthorized   = "unauthorized"
	ErrVoiceOff       = "voice_off"
	ErrTooMany        = "too_many"
	ErrBadHello       = "bad_hello"
	ErrVersion        = "unsupported_version"
	ErrBackend        = "backend_unavailable"
	ErrNotController  = "not_controller"
	ErrNotScreen      = "not_screen"
	ErrRateLimited    = "rate_limited"
	ErrBusy           = "busy"
	ErrTooLong        = "too_long"
	ErrBadFrame       = "bad_frame"
	ErrDailyAudio     = "daily_audio_limit"
	ErrReplaced       = "replaced"
	ErrRevoked        = "revoked"
	ErrNoListen       = "no_listen"
	ErrHelloTimeout   = "hello_timeout"
	ErrIdleTimeout    = "idle_timeout"
	ErrServerShutdown = "shutdown"
)

// Envelope reads only the type of a frame.
type Envelope struct {
	T string `json:"t"`
}

// Hello is the first frame of a device.
type Hello struct {
	V       int      `json:"v"`
	Token   string   `json:"token"`
	Roles   []string `json:"roles"`
	Client  string   `json:"client"`
	Name    string   `json:"name"`
	Tools   []string `json:"tools"`
	Mic     bool     `json:"mic"`
	Speaker bool     `json:"speaker"`
}

// Video is the subset of a video the live server looks at.
type Video struct {
	ID        string  `json:"id"`
	Title     string  `json:"title"`
	Channel   string  `json:"channel"`
	DurationS float64 `json:"duration_s"`
}

// Cut is the cut state of the focused video.
type Cut struct {
	Active    bool   `json:"active"`
	Label     string `json:"label"`
	Part      int    `json:"part"`
	Parts     int    `json:"parts"`
	PresetID  string `json:"preset_id,omitempty"`
	RequestID string `json:"request_id,omitempty"`
}

// Focus is what a screen reports about itself.
type Focus struct {
	Seq       int64   `json:"seq"`
	Screen    string  `json:"screen"`
	Video     *Video  `json:"video"`
	PositionS float64 `json:"position_s"`
	Playing   bool    `json:"playing"`
	Rate      float64 `json:"rate"`
	Cut       *Cut    `json:"cut"`
	Captions  *struct {
		Track string `json:"track"`
	} `json:"captions"`
	View string `json:"view"`
	AtMs int64  `json:"at_ms"`
}

// Listen starts, ends or cancels an utterance.
type Listen struct {
	ID     string `json:"id"`
	State  string `json:"state"`
	Format string `json:"format"`
	Target string `json:"target"`
	T0Ms   int64  `json:"t0_ms"`
}

// Say is a typed command.
type Say struct {
	ID     string `json:"id"`
	Text   string `json:"text"`
	Target string `json:"target"`
}

// Ack is a screen's answer to a command.
type Ack struct {
	ID      string          `json:"id"`
	State   string          `json:"state"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data"`
}

// Answer picks an option of an ask or a confirmation.
type Answer struct {
	ID     string `json:"id"`
	Option string `json:"option"`
}

// Ping and pong carry the sender's clock.
type Ping struct {
	TS int64 `json:"ts"`
}

// Ack states.
const (
	AckReceived     = "received"
	AckConfirmShown = "confirm_shown"
	AckStarted      = "started"
	AckDone         = "done"
	AckFailed       = "failed"
	AckRefused      = "refused"
)

// Listen states.
const (
	ListenStart  = "start"
	ListenEnd    = "end"
	ListenCancel = "cancel"
)

// Heard states.
const (
	HeardListening    = "listening"
	HeardTranscribing = "transcribing"
	HeardUnderstood   = "understood"
	HeardFailed       = "failed"
)

// Outcomes of a command, as the history route takes them.
const (
	OutcomeOK        = "ok"
	OutcomeFailed    = "failed"
	OutcomeCancelled = "cancelled"
	OutcomeRefused   = "refused"
	OutcomeClarify   = "clarify"
	OutcomeNone      = "none"
)

// Out is a generic outbound frame builder.
type Out map[string]any

// New starts an outbound frame of a type.
func New(t string) Out { return Out{"t": t} }

// With sets a key and returns the frame.
func (o Out) With(k string, v any) Out { o[k] = v; return o }

// Peer describes another device of the user.
type Peer struct {
	DeviceID string          `json:"device_id"`
	Name     string          `json:"name"`
	Roles    []string        `json:"roles"`
	Client   string          `json:"client"`
	Focus    json.RawMessage `json:"focus,omitempty"`
}
