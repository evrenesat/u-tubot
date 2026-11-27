package bench

import (
	"testing"
	"time"
)

// The done-when of checkpoint 2: the live server's own time is under 20 ms at the 99th percentile on loopback,
// with a few hundred idle sockets held next to the busy ones.
func TestServerTimeIsUnderTheBudget(t *testing.T) {
	res, err := Run(Options{Commands: 2000, Users: 4, Idle: 100})
	if err != nil {
		t.Fatal(err)
	}
	t.Log("\n" + res.Table())
	if res.Commands < 2000 {
		t.Fatalf("only %d commands were measured", res.Commands)
	}
	budget := float64(DefaultMaxP99 / time.Millisecond)
	if res.Server.P99 > budget {
		t.Fatalf("server time p99 %.3f ms is over %.0f ms", res.Server.P99, budget)
	}
}
