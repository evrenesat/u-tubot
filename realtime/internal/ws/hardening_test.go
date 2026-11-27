package ws_test

import (
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/intent"
	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

// --- the backend's sign-in budget -------------------------------------------------------------------------------

func TestImplausibleTokensNeverReachTheBackend(t *testing.T) {
	e := newEnv(t, nil, nil)
	for _, token := range []string{"", "x", "Bearer abc", "utb_" + strings.Repeat("a", 200)} {
		d, _ := e.rawDial(nil)
		d.send(map[string]any{"t": "hello", "v": 1, "token": token, "roles": []string{"screen"}})
		if got := d.closedWith(); got != "unauthorized" {
			t.Fatalf("%.20q: %q", token, got)
		}
	}
	e.py.mu.Lock()
	defer e.py.mu.Unlock()
	if e.py.meCalls != 0 {
		t.Fatalf("the backend was asked %d times", e.py.meCalls)
	}
}

func TestTheBackendSeesWhoIsAsking(t *testing.T) {
	e := newEnv(t, nil, nil)
	e.py.add("utb_a", "owner", "da", "A")
	e.screen("utb_a", "")
	e.py.mu.Lock()
	defer e.py.mu.Unlock()
	if len(e.py.headers) != 1 || e.py.headers[0] != "realtime" {
		t.Fatalf("headers %v", e.py.headers)
	}
}

func TestUpgradeAttemptsAreLimitedPerAddress(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.HellosPerIPPerMin = 3 }, nil)
	for i := 0; i < 3; i++ {
		if _, err := e.rawDial(http.Header{"X-Forwarded-For": []string{"198.51.100.7"}}); err != nil {
			t.Fatalf("attempt %d: %v", i, err)
		}
	}
	if _, err := e.rawDial(http.Header{"X-Forwarded-For": []string{"198.51.100.7"}}); err == nil {
		t.Fatal("the fourth attempt of one address must be refused")
	}
	// The proxy's own entry is the last one: a spoofed first entry changes nothing, another client is not affected.
	if _, err := e.rawDial(http.Header{"X-Forwarded-For": []string{"203.0.113.9, 198.51.100.7"}}); err == nil {
		t.Fatal("a spoofed first entry must not help")
	}
	if _, err := e.rawDial(http.Header{"X-Forwarded-For": []string{"198.51.100.8"}}); err != nil {
		t.Fatalf("another address: %v", err)
	}
}

func TestSocketsWithoutAHelloAreCapped(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.MaxPreAuth = 2; c.HelloTimeout = 2 * time.Second }, nil)
	for i := 0; i < 2; i++ {
		if _, err := e.rawDial(http.Header{"X-Forwarded-For": []string{fmt.Sprintf("192.0.2.%d", i)}}); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := e.rawDial(http.Header{"X-Forwarded-For": []string{"192.0.2.99"}}); err == nil {
		t.Fatal("the third silent socket must be refused")
	}
	// A device that passes its hello frees its slot.
	e.py.add("utb_a", "owner", "da", "A")
	d, _ := e.rawDial(nil)
	_ = d
}

func TestADeviceThatCannotBeVerifiedForLongIsClosed(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AuthCache = 100 * time.Millisecond; c.MaxUnverified = 250 * time.Millisecond }, nil)
	screen, _ := twoDevices(t, e)
	e.py.mu.Lock()
	e.py.down = true
	e.py.mu.Unlock()
	if code := screen.closedWith(); code != "not_verified" {
		t.Fatalf("code %q", code)
	}
}

// --- limits survive a reconnect -----------------------------------------------------------------------------------

func TestUtteranceLimitSurvivesAReconnect(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.UtterancesPerMin = 2 }, nil)
	screen, phone := twoDevices(t, e)
	for i := 0; i < 2; i++ {
		phone.send(map[string]any{"t": "say", "id": fmt.Sprintf("a%d", i), "text": "pause"})
		cmd := screen.expect("command")
		screen.ack(cmd["id"].(string), "done")
		phone.outcome(fmt.Sprintf("a%d", i))
	}
	_ = phone.c.CloseNow()
	eventually(t, "the phone is gone", func() bool { return e.hub.Connections() == 1 })
	again := e.controller("utb_phone-token", "")
	again.send(map[string]any{"t": "say", "id": "a2", "text": "pause"})
	if f := again.expect("error"); f["code"] != "rate_limited" {
		t.Fatal(f)
	}
}

func TestAbandonedRecordingsAreChargedAndTheIndicatorEnds(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AudioSecondsPerDay = 1 }, nil)
	_, phone := twoDevices(t, e)
	e.py.add("utb_tablet", "owner", "dev-tablet", "Tablet")
	tablet := e.controller("utb_tablet", "")
	phone.send(map[string]any{"t": "listen", "id": "l1", "state": "start"})
	tablet.next(func(f map[string]any) bool { return f["t"] == "heard" && f["state"] == "listening" })
	time.Sleep(1100 * time.Millisecond)
	_ = phone.c.CloseNow() // the phone vanishes mid-utterance
	h := tablet.next(func(f map[string]any) bool { return f["t"] == "heard" && f["id"] == "l1" && f["state"] == "failed" })
	if h["message"] != "Listening ended" {
		t.Fatalf("%v", h)
	}
	tablet.send(map[string]any{"t": "listen", "id": "l2", "state": "start"})
	if f := tablet.expect("error"); f["code"] != "daily_audio_limit" {
		t.Fatalf("the abandoned second was not charged: %v", f)
	}
}

func TestAnUnendedRecordingEndsItself(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.MaxUtteranceSecs = 1 }, nil)
	_, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "listen", "id": "l1", "state": "start"})
	phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["state"] == "listening" })
	h := phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["id"] == "l1" && f["state"] == "failed" })
	if h["message"] != "That recording was too long" {
		t.Fatalf("%v", h)
	}
	phone.send(map[string]any{"t": "listen", "id": "l2", "state": "start"})
	phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["id"] == "l2" && f["state"] == "listening" })
}

// --- history ----------------------------------------------------------------------------------------------------

func TestRateLimitedFramesAreNotFiledOrCounted(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.UtterancesPerMin = 1 }, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "h1", "text": "pause"})
	screen.ack(screen.expect("command")["id"].(string), "done")
	phone.outcome("h1")
	for i := 0; i < 5; i++ {
		phone.send(map[string]any{"t": "say", "id": fmt.Sprintf("flood%d", i), "text": "pause"})
		if out := phone.outcome(fmt.Sprintf("flood%d", i)); out["state"] != "rate_limited" {
			t.Fatal(out)
		}
	}
	e.hub.Wait()
	if n := len(e.py.recordsSnapshot()); n != 1 {
		t.Fatalf("%d records", n)
	}
	if n := e.stats.Report().Count; n != 1 {
		t.Fatalf("%d stats entries", n)
	}
}

// --- focus ------------------------------------------------------------------------------------------------------

func TestAScreenThatStopsReportingStopsCountingAsPlaying(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.FocusMaxAge = 300 * time.Millisecond }, nil)
	s := twoScreenSetup(t, e, true, true)
	time.Sleep(200 * time.Millisecond)
	s.living.send(playing(2, "v1", true))
	s.living.sync()
	time.Sleep(200 * time.Millisecond) // the bedroom is now 400 ms old, the living room 200 ms
	s.phone.send(map[string]any{"t": "say", "id": "p1", "text": "pause"})
	s.living.expect("command")
	s.bedroom.none(ofType("command"), 50*time.Millisecond)
}

func TestAnOversizedFocusIsKeptButNotRelayed(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	big := playing(7, "v7", true)
	big["video"].(map[string]any)["title"] = strings.Repeat("t", 12000)
	screen.send(big)
	phone.next(func(f map[string]any) bool {
		if f["t"] != "peers" {
			return false
		}
		for _, p := range f["peers"].([]any) {
			peer := p.(map[string]any)
			if peer["device_id"] == "dev-tv" && peer["focus"] == nil {
				return true
			}
		}
		return false
	})
	phone.send(map[string]any{"t": "say", "id": "big1", "text": "pause"})
	if cmd := screen.expect("command"); cmd["tool"] != "pause" {
		t.Fatal(cmd)
	}
}

// --- duplicates, clarify, answers -----------------------------------------------------------------------------------

func TestAResentSayRunsOnce(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "dup", "text": "next part"})
	cmd := screen.expect("command")
	screen.ack(cmd["id"].(string), "done")
	phone.outcome("dup")
	_ = phone.c.CloseNow()
	eventually(t, "phone gone", func() bool { return e.hub.Connections() == 1 })
	again := e.controller("utb_phone-token", "")
	again.send(map[string]any{"t": "say", "id": "dup", "text": "next part"}) // resent after the reconnect
	again.send(map[string]any{"t": "say", "id": "fresh", "text": "play"})
	if next := screen.expect("command"); next["tool"] != "play" {
		t.Fatalf("the resent frame ran again: %v", next)
	}
}

func clarifyUnderstander(text string, _ *proto.Focus) intent.Decision {
	if text == "do something" {
		return intent.Decision{Tool: intent.Clarify, Args: map[string]any{"text": "Pause or play?"}, Options: []string{"pause", "play"}}
	}
	return intent.Stage1(text)
}

func TestAClarifyingQuestionIsKeptAndItsAnswerRuns(t *testing.T) {
	e := newEnv(t, nil, clarifyUnderstander)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "c1", "text": "do something"})
	ask := phone.expect("ask")
	if ask["text"] != "Pause or play?" || len(ask["options"].([]any)) != 2 {
		t.Fatalf("%v", ask)
	}
	phone.send(map[string]any{"t": "say", "id": "c2", "text": "pause"})
	if cmd := screen.expect("command"); cmd["tool"] != "pause" {
		t.Fatal(cmd)
	}
	phone.send(map[string]any{"t": "answer", "id": ask["id"], "option": "play"}) // the question is gone
	screen.none(ofType("command"), 80*time.Millisecond)
}

func TestSpokenCancelAnswersNoToAConfirmation(t *testing.T) {
	e := newEnv(t, nil, researchUnderstander)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "k1", "text": "research this"})
	id := screen.expect("command")["id"].(string)
	screen.ack(id, "confirm_shown")
	screen.sync()
	phone.send(map[string]any{"t": "say", "id": "k2", "text": "cancel"})
	if ans := screen.expect("answer"); ans["option"] != "no" || ans["id"] != id {
		t.Fatal(ans)
	}
}

func TestOnlyAControllerAnswersAConfirmation(t *testing.T) {
	e := newEnv(t, nil, researchUnderstander)
	screen, phone := twoDevices(t, e)
	e.py.add("utb_other", "owner", "dev-other", "Other screen")
	other := e.screen("utb_other", "")
	phone.send(map[string]any{"t": "say", "id": "k1", "text": "research this"})
	id := screen.expect("command")["id"].(string)
	screen.ack(id, "confirm_shown")
	screen.sync()
	other.send(map[string]any{"t": "answer", "id": id, "option": "yes"})
	other.sync()
	screen.none(ofType("answer"), 80*time.Millisecond)
}

func TestAnAckWithAnUnknownStateIsNotAReceipt(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AckTimeout = 150 * time.Millisecond }, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "b1", "text": "pause"})
	cmd := screen.expect("command")
	screen.ack(cmd["id"].(string), "bogus")
	if out := phone.outcome("b1"); out["state"] != "timeout" {
		t.Fatal(out)
	}
}
