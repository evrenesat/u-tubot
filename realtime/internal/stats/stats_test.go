package stats

import (
	"testing"
	"time"
)

func TestComputeNearestRank(t *testing.T) {
	var ds []time.Duration
	for i := 1; i <= 100; i++ {
		ds = append(ds, time.Duration(i)*time.Millisecond)
	}
	p := Compute(ds)
	if p.N != 100 || p.P50 != 50 || p.P90 != 90 || p.P99 != 99 || p.Max != 100 {
		t.Fatalf("%+v", p)
	}
	if (Compute(nil) != Percentiles{}) {
		t.Fatal("empty")
	}
}

func TestRingKeepsTheLastWindowAndGroupsByFamily(t *testing.T) {
	s := New(3)
	for i := 1; i <= 5; i++ {
		fam := "player"
		if i == 5 {
			fam = "cut"
		}
		s.Add(Record{Tool: "x", Family: fam, Outcome: "ok", Hops: map[string]time.Duration{HopServer: time.Duration(i) * time.Millisecond}})
	}
	rep := s.Report()
	if rep.Count != 3 || rep.Hops[HopServer].Max != 5 || rep.Hops[HopServer].P50 != 4 {
		t.Fatalf("%+v", rep)
	}
	if rep.Families["cut"][HopServer].N != 1 || rep.Families["player"][HopServer].N != 2 || rep.Outcomes["ok"] != 3 {
		t.Fatalf("%+v", rep)
	}
}
