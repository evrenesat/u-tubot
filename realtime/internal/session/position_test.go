package session

import (
	"testing"
	"time"

	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

func TestPositionIsExtrapolatedFromTheLastReport(t *testing.T) {
	at := time.Unix(1000, 0)
	f := &proto.Focus{PositionS: 100, Playing: true, Rate: 1.5, Video: &proto.Video{DurationS: 130}}
	if got := PositionAt(f, at, at.Add(10*time.Second)); got != 115 {
		t.Fatalf("got %v", got)
	}
	if got := PositionAt(f, at, at.Add(60*time.Second)); got != 130 {
		t.Fatalf("clamped to the end, got %v", got)
	}
	f.Playing = false
	if got := PositionAt(f, at, at.Add(10*time.Second)); got != 100 {
		t.Fatalf("paused, got %v", got)
	}
}
