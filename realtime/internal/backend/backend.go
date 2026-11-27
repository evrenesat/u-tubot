// Package backend asks the Python backend who a token belongs to (GET /v1/me) and files finished commands.
// The live server holds no user table: a revoked device or a switched-off voice setting reaches it within the cache window.
package backend

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"
)

// Errors a check can end in.
var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrVoiceOff     = errors.New("voice is off")
	ErrUnavailable  = errors.New("backend unavailable")
)

const maxMeBytes = 1 << 20

// Identity is what the live server keeps of a token's owner.
type Identity struct {
	User          string
	DeviceID      string
	DeviceName    string
	VoiceOn       bool
	ListenMode    string
	Speak         bool
	RetentionDays int
}

// Checker resolves a device token.
type Checker interface {
	Check(ctx context.Context, token string) (Identity, error)
}

// Recorder files one command record with the token of the device that spoke.
type Recorder interface {
	Record(ctx context.Context, token string, rec Record) error
}

// Record is the body of POST /v1/voice/commands. No audio is ever part of it.
type Record struct {
	Text    string         `json:"text"`
	Tool    string         `json:"tool"`
	Args    map[string]any `json:"args"`
	Outcome string         `json:"outcome"`
	Marks   map[string]int `json:"marks"`
}

type meResponse struct {
	User     string `json:"user"`
	Features struct {
		Voice bool `json:"voice"`
	} `json:"features"`
	Device *struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	} `json:"device"`
	Voice *struct {
		Enabled       bool   `json:"enabled"`
		ListenMode    string `json:"listen_mode"`
		Speak         bool   `json:"speak"`
		RetentionDays int    `json:"retention_days"`
	} `json:"voice"`
}

type cached struct {
	id  Identity
	err error
	at  time.Time
}

// Client talks to the backend with a kept-alive connection pool.
type Client struct {
	base    string
	http    *http.Client
	ttl     time.Duration
	now     func() time.Time
	mu      sync.Mutex
	entries map[[32]byte]cached
}

// New builds a client for the backend at base (no trailing slash).
func New(base string, timeout, cacheTTL time.Duration) *Client {
	return &Client{
		base:    base,
		http:    &http.Client{Timeout: timeout},
		ttl:     cacheTTL,
		now:     time.Now,
		entries: map[[32]byte]cached{},
	}
}

// Check returns the identity behind a token, from the cache when it is younger than the cache window.
// Refusals (unauthorized, voice off) are cached too; an unreachable backend is not, and an older good answer
// is kept in use while the backend is unreachable.
func (c *Client) Check(ctx context.Context, token string) (Identity, error) {
	key := sha256.Sum256([]byte(token))
	c.mu.Lock()
	hit, ok := c.entries[key]
	c.mu.Unlock()
	if ok && c.now().Sub(hit.at) < c.ttl {
		return hit.id, hit.err
	}
	id, err := c.fetch(ctx, token)
	if errors.Is(err, ErrUnavailable) {
		if ok && hit.err == nil {
			return hit.id, nil
		}
		return Identity{}, err
	}
	c.mu.Lock()
	c.entries[key] = cached{id: id, err: err, at: c.now()}
	for k, v := range c.entries {
		if c.now().Sub(v.at) > 4*c.ttl {
			delete(c.entries, k)
		}
	}
	c.mu.Unlock()
	return id, err
}

func (c *Client) fetch(ctx context.Context, token string) (Identity, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/v1/me", nil)
	if err != nil {
		return Identity{}, ErrUnavailable
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := c.http.Do(req)
	if err != nil {
		return Identity{}, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()
	switch {
	case resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden:
		return Identity{}, ErrUnauthorized
	case resp.StatusCode != http.StatusOK:
		return Identity{}, fmt.Errorf("%w: status %d", ErrUnavailable, resp.StatusCode)
	}
	var me meResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxMeBytes)).Decode(&me); err != nil {
		return Identity{}, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	if me.User == "" {
		return Identity{}, ErrUnauthorized
	}
	id := Identity{User: me.User}
	if me.Device != nil {
		id.DeviceID, id.DeviceName = me.Device.ID, me.Device.Name
	}
	if !me.Features.Voice || me.Voice == nil || !me.Voice.Enabled {
		return id, ErrVoiceOff
	}
	id.VoiceOn, id.ListenMode, id.Speak, id.RetentionDays = true, me.Voice.ListenMode, me.Voice.Speak, me.Voice.RetentionDays
	return id, nil
}

// Record files a command record. It is called after the command ended, never on the live path.
func (c *Client) Record(ctx context.Context, token string, rec Record) error {
	body, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/v1/voice/commands", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("history: status %d", resp.StatusCode)
	}
	return nil
}
