// Package stats keeps the marks of the last commands and answers percentiles per hop and per tool family
// (plan 2.5, GET /rt/v1/stats). Everything is in memory; nothing is written to disk.
package stats

import (
	"math"
	"sort"
	"sync"
	"time"
)

// Hop names, in the order of the plan's table.
const (
	HopServer = "server"   // t_in to t4 minus the time spent waiting behind another command: the live server's own time
	HopPush   = "push_ack" // t4 to t5: command written to the screen's socket until received
	HopAct    = "act"      // t5 to t6: the screen acts
	HopTotal  = "total"    // say received to the end state
	HopQueue  = "queue"    // time waiting behind another command of the same screen
)

// Hops lists every hop.
var Hops = []string{HopServer, HopPush, HopAct, HopTotal, HopQueue}

// Record is one finished command.
type Record struct {
	Tool    string
	Family  string
	Outcome string
	Hops    map[string]time.Duration
}

// Percentiles of one hop, in milliseconds.
type Percentiles struct {
	N   int     `json:"n"`
	P50 float64 `json:"p50_ms"`
	P90 float64 `json:"p90_ms"`
	P99 float64 `json:"p99_ms"`
	Max float64 `json:"max_ms"`
}

// Report is the answer of the stats route.
type Report struct {
	Count    int                               `json:"count"`
	Window   int                               `json:"window"`
	Outcomes map[string]int                    `json:"outcomes"`
	Hops     map[string]Percentiles            `json:"hops"`
	Families map[string]map[string]Percentiles `json:"families"`
}

// Store is a ring of the last records.
type Store struct {
	mu     sync.Mutex
	ring   []Record
	next   int
	filled bool
}

// New keeps the last window records.
func New(window int) *Store { return &Store{ring: make([]Record, window)} }

// Add stores a record, overwriting the oldest.
func (s *Store) Add(r Record) {
	s.mu.Lock()
	s.ring[s.next] = r
	s.next++
	if s.next == len(s.ring) {
		s.next, s.filled = 0, true
	}
	s.mu.Unlock()
}

func (s *Store) snapshot() []Record {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.filled {
		return append([]Record(nil), s.ring...)
	}
	return append([]Record(nil), s.ring[:s.next]...)
}

// Records returns a copy of the stored records, oldest first only until the ring wraps.
func (s *Store) Records() []Record { return s.snapshot() }

// Report computes the percentiles over the stored records.
func (s *Store) Report() Report {
	records := s.snapshot()
	rep := Report{
		Count: len(records), Window: len(s.ring), Outcomes: map[string]int{},
		Hops: map[string]Percentiles{}, Families: map[string]map[string]Percentiles{},
	}
	byHop := map[string][]time.Duration{}
	byFamily := map[string]map[string][]time.Duration{}
	for _, r := range records {
		rep.Outcomes[r.Outcome]++
		if byFamily[r.Family] == nil {
			byFamily[r.Family] = map[string][]time.Duration{}
		}
		for hop, d := range r.Hops {
			byHop[hop] = append(byHop[hop], d)
			byFamily[r.Family][hop] = append(byFamily[r.Family][hop], d)
		}
	}
	for hop, ds := range byHop {
		rep.Hops[hop] = Compute(ds)
	}
	for fam, hops := range byFamily {
		rep.Families[fam] = map[string]Percentiles{}
		for hop, ds := range hops {
			rep.Families[fam][hop] = Compute(ds)
		}
	}
	return rep
}

// Compute returns nearest-rank percentiles, like the plan's measurements.
func Compute(ds []time.Duration) Percentiles {
	if len(ds) == 0 {
		return Percentiles{}
	}
	sorted := append([]time.Duration(nil), ds...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i] < sorted[j] })
	pick := func(q float64) float64 {
		rank := int(math.Ceil(q * float64(len(sorted))))
		if rank < 1 {
			rank = 1
		}
		return ms(sorted[rank-1])
	}
	return Percentiles{N: len(sorted), P50: pick(0.50), P90: pick(0.90), P99: pick(0.99), Max: ms(sorted[len(sorted)-1])}
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000 }
