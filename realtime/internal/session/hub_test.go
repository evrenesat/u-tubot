package session

import (
	"context"
	"testing"

	"github.com/evrenesat/u-tubot/realtime/internal/backend"
	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

type nullConn struct{ closed []string }

func (c *nullConn) Send(any) bool        { return true }
func (c *nullConn) Close(code, _ string) { c.closed = append(c.closed, code) }

type gate struct{ release chan struct{} }

func (g *gate) Record(ctx context.Context, _ string, _ backend.Record) error {
	select {
	case <-g.release:
	case <-ctx.Done():
	}
	return nil
}

func TestHistoryQueueIsBoundedAndDropsWhenFull(t *testing.T) {
	cfg := config.Default()
	cfg.RecordQueue, cfg.RecordWorkers = 3, 1
	rec := &gate{release: make(chan struct{})}
	h := New(Options{Config: cfg, Recorder: rec})
	defer h.Close()
	origin := &Session{token: "utb_x"}
	for i := 0; i < 500; i++ {
		h.record(origin, "pause", "pause", nil, "ok", nil)
	}
	h.recMu.Lock()
	queued := h.recN
	h.recMu.Unlock()
	if queued > cfg.RecordQueue+cfg.RecordWorkers {
		t.Fatalf("%d records are held, the bound is %d", queued, cfg.RecordQueue+cfg.RecordWorkers)
	}
	close(rec.release)
	h.Wait()
}

func TestJoinDuringShutdownIsRefused(t *testing.T) {
	cfg := config.Default()
	h := New(Options{Config: cfg})
	defer h.Close()
	h.CloseAll(proto.ErrServerShutdown, "bye")
	s := NewSession(proto.Hello{Roles: []string{"screen"}}, backend.Identity{User: "u"}, "d1", "TV", &nullConn{})
	if code := h.Join(s); code != proto.ErrServerShutdown {
		t.Fatalf("code %q", code)
	}
}
