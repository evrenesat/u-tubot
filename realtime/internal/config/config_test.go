package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

func TestLoadFileAndEnvironment(t *testing.T) {
	path := filepath.Join(t.TempDir(), "rt.toml")
	body := `# live server
[server]
listen = "0.0.0.0:9000"   # all
backend_url = "https://utubot.example.com/"
origins = ["https://utubot.example.com", "https://tv.example.com"]

[timing]
ack_timeout = "500ms"

[limits]
max_connections_per_user = 3
`
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path, env(map[string]string{EnvAdminToken: "s3cret", EnvListen: "127.0.0.1:1"}))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Listen != "127.0.0.1:1" || cfg.BackendURL != "https://utubot.example.com" || cfg.AdminToken != "s3cret" {
		t.Fatalf("unexpected %+v", cfg)
	}
	if cfg.AckTimeout != 500*time.Millisecond || cfg.MaxConnsPerUser != 3 || len(cfg.Origins) != 2 {
		t.Fatalf("unexpected %+v", cfg)
	}
	if cfg.CommandExpiry != DefaultCommandExpiry {
		t.Fatal("defaults must stay")
	}
}

func TestLoadRejectsBadInput(t *testing.T) {
	if _, err := Load("", env(nil)); err == nil {
		t.Fatal("backend url is required")
	}
	for _, body := range []string{"[limits]\nmax_waiting = \"x\"\n", "[timing]\nack_timeout = \"soon\"\n", "[server]\nbackend_url = nope\n", "[[x]]\n"} {
		path := filepath.Join(t.TempDir(), "bad.toml")
		_ = os.WriteFile(path, []byte(body), 0o600)
		if _, err := Load(path, env(map[string]string{EnvBackendURL: "http://127.0.0.1:1"})); err == nil {
			t.Fatalf("expected an error for %q", body)
		}
	}
	if _, err := Load(filepath.Join(t.TempDir(), "missing.toml"), env(nil)); err == nil {
		t.Fatal("missing file")
	}
}
