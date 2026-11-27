// Package config reads the live server's settings: a TOML file (the subset below) and environment variables.
//
// The layout of the loader (a defaults struct, a file merged over it, the environment on top, one validation step)
// follows the configuration package of R2T4's server (MIT, see THIRD_PARTY.md); the file format is TOML, not JSON.
package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// Environment variables. Secrets never come from the file.
const (
	EnvAdminToken = "UTUBOT_RT_ADMIN_TOKEN"
	EnvListen     = "UTUBOT_RT_LISTEN"
	EnvBackendURL = "UTUBOT_RT_BACKEND_URL"
)

// Defaults of the plan (ai/VOICE_CONTROL_PLAN.md, 2.3 and 2.5).
const (
	DefaultListen             = "127.0.0.1:8791"
	DefaultPath               = "/rt"
	DefaultHelloTimeout       = 5 * time.Second
	DefaultPingInterval       = 20 * time.Second
	DefaultIdleTimeout        = 45 * time.Second
	DefaultAuthCache          = 60 * time.Second
	DefaultBackendTimeout     = 3 * time.Second
	DefaultAckTimeout         = 2 * time.Second
	DefaultDoneTimeout        = 30 * time.Second
	DefaultCommandExpiry      = 10 * time.Second
	DefaultConfirmWindow      = 15 * time.Second
	DefaultAskWindow          = 30 * time.Second
	DefaultRecentFocus        = 10 * time.Minute
	DefaultMaxConnsPerUser    = 8
	DefaultUtterancesPerMin   = 20
	DefaultAudioSecondsPerDay = 30 * 60
	DefaultMaxFrameBytes      = 64 * 1024
	DefaultMaxUtteranceBytes  = 2 * 1024 * 1024
	DefaultMaxUtteranceSecs   = 30
	DefaultMaxWaiting         = 3
	DefaultMaxTextChars       = 2000
	DefaultStatsWindow        = 1000
	DefaultOutQueue           = 64
	DefaultShutdownGrace      = 10 * time.Second
)

// Config is the whole configuration.
type Config struct {
	Listen         string
	Path           string
	BackendURL     string
	Origins        []string
	AdminToken     string
	HelloTimeout   time.Duration
	PingInterval   time.Duration
	IdleTimeout    time.Duration
	AuthCache      time.Duration
	BackendTimeout time.Duration

	AckTimeout    time.Duration
	DoneTimeout   time.Duration
	CommandExpiry time.Duration
	ConfirmWindow time.Duration
	AskWindow     time.Duration
	RecentFocus   time.Duration
	MaxWaiting    int

	MaxConnsPerUser    int
	UtterancesPerMin   int
	AudioSecondsPerDay int
	MaxFrameBytes      int
	MaxUtteranceBytes  int
	MaxUtteranceSecs   int
	MaxTextChars       int

	StatsWindow   int
	OutQueue      int
	ShutdownGrace time.Duration
}

// Default returns the plan's values.
func Default() Config {
	return Config{
		Listen:             DefaultListen,
		Path:               DefaultPath,
		HelloTimeout:       DefaultHelloTimeout,
		PingInterval:       DefaultPingInterval,
		IdleTimeout:        DefaultIdleTimeout,
		AuthCache:          DefaultAuthCache,
		BackendTimeout:     DefaultBackendTimeout,
		AckTimeout:         DefaultAckTimeout,
		DoneTimeout:        DefaultDoneTimeout,
		CommandExpiry:      DefaultCommandExpiry,
		ConfirmWindow:      DefaultConfirmWindow,
		AskWindow:          DefaultAskWindow,
		RecentFocus:        DefaultRecentFocus,
		MaxWaiting:         DefaultMaxWaiting,
		MaxConnsPerUser:    DefaultMaxConnsPerUser,
		UtterancesPerMin:   DefaultUtterancesPerMin,
		AudioSecondsPerDay: DefaultAudioSecondsPerDay,
		MaxFrameBytes:      DefaultMaxFrameBytes,
		MaxUtteranceBytes:  DefaultMaxUtteranceBytes,
		MaxUtteranceSecs:   DefaultMaxUtteranceSecs,
		MaxTextChars:       DefaultMaxTextChars,
		StatsWindow:        DefaultStatsWindow,
		OutQueue:           DefaultOutQueue,
		ShutdownGrace:      DefaultShutdownGrace,
	}
}

// Load reads the file at path (empty: none) and the environment.
func Load(path string, getenv func(string) string) (Config, error) {
	cfg := Default()
	if path != "" {
		raw, err := os.ReadFile(path)
		if err != nil {
			return cfg, fmt.Errorf("reading %s: %w", path, err)
		}
		doc, err := ParseTOML(string(raw))
		if err != nil {
			return cfg, fmt.Errorf("parsing %s: %w", path, err)
		}
		if err := apply(&cfg, doc); err != nil {
			return cfg, err
		}
	}
	if v := getenv(EnvListen); v != "" {
		cfg.Listen = v
	}
	if v := getenv(EnvBackendURL); v != "" {
		cfg.BackendURL = v
	}
	if v := getenv(EnvAdminToken); v != "" {
		cfg.AdminToken = v
	}
	return cfg, cfg.Validate()
}

// Validate checks the values the server cannot run without.
func (c *Config) Validate() error {
	u, err := url.Parse(c.BackendURL)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return fmt.Errorf("backend_url must be an http(s) address, got %q", c.BackendURL)
	}
	c.BackendURL = strings.TrimRight(c.BackendURL, "/")
	if !strings.HasPrefix(c.Path, "/") {
		return fmt.Errorf("path must start with /, got %q", c.Path)
	}
	c.Path = strings.TrimRight(c.Path, "/")
	positive := map[string]int{
		"max_waiting": c.MaxWaiting, "max_connections_per_user": c.MaxConnsPerUser, "utterances_per_minute": c.UtterancesPerMin,
		"audio_seconds_per_day": c.AudioSecondsPerDay, "max_frame_bytes": c.MaxFrameBytes, "max_utterance_bytes": c.MaxUtteranceBytes,
		"max_utterance_seconds": c.MaxUtteranceSecs, "stats_window": c.StatsWindow, "out_queue": c.OutQueue, "max_text_chars": c.MaxTextChars,
	}
	for name, v := range positive {
		if v <= 0 {
			return fmt.Errorf("%s must be positive", name)
		}
	}
	return nil
}

func apply(cfg *Config, doc map[string]map[string]any) error {
	var firstErr error
	fail := func(err error) {
		if firstErr == nil {
			firstErr = err
		}
	}
	str := func(dst *string, sec, key string) {
		if v, ok := doc[sec][key]; ok {
			s, isStr := v.(string)
			if !isStr {
				fail(fmt.Errorf("%s.%s must be a string", sec, key))
				return
			}
			*dst = s
		}
	}
	num := func(dst *int, sec, key string) {
		if v, ok := doc[sec][key]; ok {
			n, isNum := v.(int)
			if !isNum {
				fail(fmt.Errorf("%s.%s must be an integer", sec, key))
				return
			}
			*dst = n
		}
	}
	dur := func(dst *time.Duration, sec, key string) {
		if v, ok := doc[sec][key]; ok {
			s, isStr := v.(string)
			if !isStr {
				fail(fmt.Errorf("%s.%s must be a duration string such as \"5s\"", sec, key))
				return
			}
			d, err := time.ParseDuration(s)
			if err != nil {
				fail(fmt.Errorf("%s.%s: %w", sec, key, err))
				return
			}
			*dst = d
		}
	}
	str(&cfg.Listen, "server", "listen")
	str(&cfg.Path, "server", "path")
	str(&cfg.BackendURL, "server", "backend_url")
	if v, ok := doc["server"]["origins"]; ok {
		list, isList := v.([]string)
		if !isList {
			fail(fmt.Errorf("server.origins must be a list of strings"))
		}
		cfg.Origins = list
	}
	dur(&cfg.HelloTimeout, "timing", "hello_timeout")
	dur(&cfg.PingInterval, "timing", "ping_interval")
	dur(&cfg.IdleTimeout, "timing", "idle_timeout")
	dur(&cfg.AuthCache, "timing", "auth_cache")
	dur(&cfg.BackendTimeout, "timing", "backend_timeout")
	dur(&cfg.AckTimeout, "timing", "ack_timeout")
	dur(&cfg.DoneTimeout, "timing", "done_timeout")
	dur(&cfg.CommandExpiry, "timing", "command_expiry")
	dur(&cfg.ConfirmWindow, "timing", "confirm_window")
	dur(&cfg.AskWindow, "timing", "ask_window")
	dur(&cfg.RecentFocus, "timing", "recent_focus")
	num(&cfg.MaxWaiting, "limits", "max_waiting")
	num(&cfg.MaxConnsPerUser, "limits", "max_connections_per_user")
	num(&cfg.UtterancesPerMin, "limits", "utterances_per_minute")
	num(&cfg.AudioSecondsPerDay, "limits", "audio_seconds_per_day")
	num(&cfg.MaxFrameBytes, "limits", "max_frame_bytes")
	num(&cfg.MaxUtteranceBytes, "limits", "max_utterance_bytes")
	num(&cfg.MaxUtteranceSecs, "limits", "max_utterance_seconds")
	num(&cfg.MaxTextChars, "limits", "max_text_chars")
	num(&cfg.StatsWindow, "limits", "stats_window")
	return firstErr
}

// ParseTOML reads the small subset the live server needs: [sections], key = "string" | integer | true | false |
// ["list", "of", "strings"], and # comments. Everything else is an error, so a typo is not silently ignored.
func ParseTOML(text string) (map[string]map[string]any, error) {
	doc := map[string]map[string]any{"": {}}
	section := ""
	for n, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(stripComment(line))
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "[") {
			if !strings.HasSuffix(line, "]") || strings.HasPrefix(line, "[[") {
				return nil, fmt.Errorf("line %d: unsupported table %q", n+1, line)
			}
			section = strings.TrimSpace(line[1 : len(line)-1])
			if doc[section] == nil {
				doc[section] = map[string]any{}
			}
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return nil, fmt.Errorf("line %d: expected key = value", n+1)
		}
		parsed, err := parseValue(strings.TrimSpace(value))
		if err != nil {
			return nil, fmt.Errorf("line %d: %w", n+1, err)
		}
		doc[section][strings.TrimSpace(key)] = parsed
	}
	return doc, nil
}

func stripComment(line string) string {
	inString := false
	for i, r := range line {
		switch {
		case r == '"':
			inString = !inString
		case r == '#' && !inString:
			return line[:i]
		}
	}
	return line
}

func parseValue(v string) (any, error) {
	switch {
	case v == "true":
		return true, nil
	case v == "false":
		return false, nil
	case strings.HasPrefix(v, "["):
		if !strings.HasSuffix(v, "]") {
			return nil, fmt.Errorf("unterminated list")
		}
		items := []string{}
		inner := strings.TrimSpace(v[1 : len(v)-1])
		if inner == "" {
			return items, nil
		}
		for _, part := range strings.Split(inner, ",") {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			s, err := strconv.Unquote(part)
			if err != nil {
				return nil, fmt.Errorf("list items must be quoted strings, got %s", part)
			}
			items = append(items, s)
		}
		return items, nil
	case strings.HasPrefix(v, "\""):
		s, err := strconv.Unquote(v)
		if err != nil {
			return nil, fmt.Errorf("bad string %s", v)
		}
		return s, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return nil, fmt.Errorf("unsupported value %q", v)
	}
	return n, nil
}
