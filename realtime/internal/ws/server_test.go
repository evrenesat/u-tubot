package ws_test

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/evrenesat/u-tubot/realtime/internal/config"
	"github.com/evrenesat/u-tubot/realtime/internal/intent"
	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

func twoDevices(t *testing.T, e *env) (screen, phone *tc) {
	t.Helper()
	e.py.add("utb_tv-token", "owner", "dev-tv", "Living room TV")
	e.py.add("utb_phone-token", "owner", "dev-phone", "Phone")
	screen = e.screen("utb_tv-token", "")
	screen.send(playing(1, "v1", true))
	screen.sync()
	phone = e.controller("utb_phone-token", "")
	return
}

func (d *tc) ack(id, state string) {
	d.send(map[string]any{"t": "ack", "id": id, "state": state})
}

// --- hello ------------------------------------------------------------------------------------------------------

func TestHelloRefusals(t *testing.T) {
	e := newEnv(t, nil, nil)
	e.py.add("utb_good", "owner", "d1", "TV")
	e.py.tokens["utb_off"] = fakeMe{user: "owner", device: "d2", name: "TV 2", voiceFeature: true, on: false}
	e.py.tokens["utb_novoice"] = fakeMe{user: "owner", device: "d3", name: "TV 3"}

	cases := []struct {
		name  string
		hello map[string]any
		code  string
	}{
		{"unknown token", map[string]any{"t": "hello", "v": 1, "token": "utb_nope", "roles": []string{"screen"}}, "unauthorized"},
		{"no token", map[string]any{"t": "hello", "v": 1, "roles": []string{"screen"}}, "unauthorized"},
		{"device has not switched voice on", map[string]any{"t": "hello", "v": 1, "token": "utb_off", "roles": []string{"screen"}}, "voice_off"},
		{"server has voice off", map[string]any{"t": "hello", "v": 1, "token": "utb_novoice", "roles": []string{"screen"}}, "voice_off"},
		{"wrong version", map[string]any{"t": "hello", "v": 2, "token": "utb_good", "roles": []string{"screen"}}, "unsupported_version"},
		{"no roles", map[string]any{"t": "hello", "v": 1, "token": "utb_good", "roles": []string{"toaster"}}, "bad_hello"},
		{"first frame is not hello", map[string]any{"t": "focus"}, "bad_hello"},
	}
	for _, c := range cases {
		d, err := e.rawDial(nil)
		if err != nil {
			t.Fatal(err)
		}
		d.send(c.hello)
		if got := d.closedWith(); got != c.code {
			t.Errorf("%s: code %q, want %q", c.name, got, c.code)
		}
	}
}

func TestHelloTimeoutAndBackendDown(t *testing.T) {
	e := newEnv(t, nil, nil)
	silent, _ := e.rawDial(nil)
	if got := silent.closedWith(); got != "hello_timeout" {
		t.Fatalf("code %q", got)
	}
	e.py.add("utb_good", "owner", "d1", "TV")
	e.py.mu.Lock()
	e.py.down = true
	e.py.mu.Unlock()
	d, _ := e.rawDial(nil)
	d.send(map[string]any{"t": "hello", "v": 1, "token": "utb_good", "roles": []string{"screen"}})
	if got := d.closedWith(); got != "backend_unavailable" {
		t.Fatalf("code %q", got)
	}
}

func TestWelcomeCarriesConsentPeersAndClock(t *testing.T) {
	e := newEnv(t, nil, nil)
	_, phone := twoDevices(t, e)
	_ = phone
	d, w := e.connect("utb_phone-token", helloOpts{roles: []string{"controller"}, name: "Phone 2"})
	_ = d
	if w["user"] != "owner" || w["device_id"] != "dev-phone" {
		t.Fatalf("welcome %v", w)
	}
	voice := w["voice"].(map[string]any)
	if voice["enabled"] != true || voice["listen_mode"] != "push" || voice["retention_days"].(float64) != 30 {
		t.Fatalf("voice %v", voice)
	}
	peers := w["peers"].([]any)
	if len(peers) != 1 {
		t.Fatalf("peers %v", peers)
	}
	tv := peers[0].(map[string]any)
	if tv["device_id"] != "dev-tv" || tv["name"] != "Living room TV" || tv["focus"] == nil {
		t.Fatalf("tv peer %v", tv)
	}
	if ms := w["server_time_ms"].(float64); time.Since(time.UnixMilli(int64(ms))) > 5*time.Second {
		t.Fatalf("server_time_ms %v", ms)
	}
}

// --- the done-when of the checkpoint: a scripted controller pauses a scripted screen ------------------------------

func TestScriptedControllerPausesScriptedScreen(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)

	phone.send(map[string]any{"t": "say", "id": "u1", "text": "Pause, please"})
	cmd := screen.expect("command")
	if cmd["tool"] != "pause" || cmd["confirm"] != nil {
		t.Fatalf("command %v", cmd)
	}
	origin := cmd["origin"].(map[string]any)
	if origin["device_id"] != "dev-phone" || origin["kind"] != "text" {
		t.Fatalf("origin %v", origin)
	}
	if exp := time.UnixMilli(int64(cmd["expires_ms"].(float64))); time.Until(exp) <= 0 || time.Until(exp) > e.cfg.CommandExpiry {
		t.Fatalf("expires_ms %v", exp)
	}
	id := cmd["id"].(string)
	screen.ack(id, "received")
	screen.ack(id, "done")

	heard := phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["state"] == "understood" })
	if heard["id"] != "u1" || heard["text"] != "Pause, please" || heard["tool"] != "pause" {
		t.Fatalf("heard %v", heard)
	}
	out := phone.outcome("u1")
	if out["state"] != "ok" || out["tool"] != "pause" || out["command_id"] != id {
		t.Fatalf("outcome %v", out)
	}

	// The history record is filed with the speaker's own token, after the command ended, with the marks and no audio.
	e.hub.Wait()
	records := e.py.recordsSnapshot()
	if len(records) != 1 || records[0].token != "utb_phone-token" {
		t.Fatalf("records %v", records)
	}
	body := records[0].body
	if body["tool"] != "pause" || body["outcome"] != "ok" || body["text"] != "Pause, please" {
		t.Fatalf("record %v", body)
	}
	marks := body["marks"].(map[string]any)
	for _, k := range []string{"server_ms", "push_ack_ms", "act_ms", "total_ms"} {
		if _, ok := marks[k]; !ok {
			t.Fatalf("marks %v lack %s", marks, k)
		}
	}
}

func TestSeekArgumentsAndValidation(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)

	phone.send(map[string]any{"t": "say", "id": "s1", "text": "go back thirty seconds"})
	cmd := screen.expect("command")
	if cmd["tool"] != "seek" || cmd["args"].(map[string]any)["by_s"].(float64) != -30 {
		t.Fatalf("command %v", cmd)
	}
	screen.ack(cmd["id"].(string), "done")
	phone.outcome("s1")

	phone.send(map[string]any{"t": "say", "id": "s2", "text": "go to 2 hours"})
	out := phone.outcome("s2")
	if out["state"] != "refused" || out["message"] != "That is past the end of the video" {
		t.Fatalf("outcome %v", out)
	}
	screen.none(ofType("command"), 100*time.Millisecond)
}

func TestUnknownPhraseAndNoVideo(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "x1", "text": "make a cut that keeps only the benchmarks"})
	reply := phone.expect("reply")
	out := phone.outcome("x1")
	if reply["text"] != "I did not understand that" || out["state"] != "none" {
		t.Fatalf("%v %v", reply, out)
	}
	screen.send(map[string]any{"t": "focus", "seq": 2, "screen": "browse", "video": nil, "playing": false})
	screen.sync()
	phone.send(map[string]any{"t": "say", "id": "x2", "text": "pause"})
	if r := phone.expect("reply"); r["text"] != "Focus a video first" {
		t.Fatalf("%v", r)
	}
	phone.send(map[string]any{"t": "say", "id": "x3", "text": "show more"})
	if cmd := screen.expect("command"); cmd["tool"] != "show_more" {
		t.Fatalf("view tools need no video: %v", cmd)
	}
}

// --- delivery rules ---------------------------------------------------------------------------------------------

func TestOfflineScreen(t *testing.T) {
	e := newEnv(t, nil, nil)
	e.py.add("utb_phone-token", "owner", "dev-phone", "Phone")
	phone := e.controller("utb_phone-token", "")
	phone.send(map[string]any{"t": "say", "id": "o1", "text": "pause"})
	reply := phone.expect("reply")
	out := phone.outcome("o1")
	if reply["text"] != "The TV is not connected" || out["state"] != "offline" {
		t.Fatalf("%v %v", reply, out)
	}
	e.hub.Wait()
	if recs := e.py.recordsSnapshot(); len(recs) != 1 || recs[0].body["outcome"] != "failed" {
		t.Fatalf("records %v", recs)
	}
}

func TestNoReceivedInTimeKillsTheCommand(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AckTimeout = 100 * time.Millisecond }, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "n1", "text": "pause"})
	cmd := screen.expect("command")
	out := phone.outcome("n1")
	if out["state"] != "timeout" || out["message"] != "The TV did not answer" {
		t.Fatalf("%v", out)
	}
	if rev := screen.expect("revoke"); rev["id"] != cmd["id"] {
		t.Fatalf("revoke %v", rev)
	}
	// A late ack changes nothing and a new command goes through.
	screen.ack(cmd["id"].(string), "done")
	phone.send(map[string]any{"t": "say", "id": "n2", "text": "play"})
	next := screen.expect("command")
	screen.ack(next["id"].(string), "done")
	if got := phone.outcome("n2"); got["state"] != "ok" {
		t.Fatalf("%v", got)
	}
}

func TestCommandsToOneScreenRunOneAtATimeAndExpire(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.CommandExpiry = 400 * time.Millisecond; c.AckTimeout = time.Second }, nil)
	screen, phone := twoDevices(t, e)
	for i, text := range []string{"pause", "play", "next part", "previous part", "cut off"} {
		phone.send(map[string]any{"t": "say", "id": fmt.Sprintf("q%d", i), "text": text})
	}
	first := screen.expect("command")
	if first["tool"] != "pause" {
		t.Fatal(first)
	}
	// One in flight, three waiting, the fifth is refused as busy.
	if out := phone.outcome("q4"); out["state"] != "busy" {
		t.Fatalf("%v", out)
	}
	screen.none(ofType("command"), 50*time.Millisecond)
	// The screen sits on the first command; the waiting ones expire before they are ever sent.
	expired := 0
	for expired < 3 {
		out := phone.next(func(f map[string]any) bool { return f["t"] == "outcome" && f["state"] == "expired" })
		if out["id"] == "q0" || out["id"] == "q4" {
			t.Fatalf("%v", out)
		}
		expired++
	}
	screen.none(ofType("command"), 100*time.Millisecond)
	screen.ack(first["id"].(string), "done")
	if out := phone.outcome("q0"); out["state"] != "ok" {
		t.Fatalf("%v", out)
	}
}

func TestWaitingCommandRunsAfterTheFirstEnds(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "w1", "text": "pause"})
	phone.send(map[string]any{"t": "say", "id": "w2", "text": "play"})
	first := screen.expect("command")
	screen.none(ofType("command"), 50*time.Millisecond)
	screen.ack(first["id"].(string), "done")
	second := screen.expect("command")
	if second["tool"] != "play" {
		t.Fatal(second)
	}
	screen.ack(second["id"].(string), "failed")
	if out := phone.outcome("w2"); out["state"] != "failed" || out["message"] != "That did not work" {
		t.Fatalf("%v", out)
	}
}

func TestScreenMessageIsPassedBack(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "m1", "text": "next part"})
	cmd := screen.expect("command")
	screen.send(map[string]any{"t": "ack", "id": cmd["id"], "state": "refused", "message": "No cut is on"})
	if r := phone.expect("reply"); r["text"] != "No cut is on" {
		t.Fatalf("%v", r)
	}
	if out := phone.outcome("m1"); out["state"] != "refused" {
		t.Fatalf("%v", out)
	}
}

func TestReconnectNeverReplaysACommand(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AckTimeout = 5 * time.Second }, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "r1", "text": "pause"})
	screen.expect("command")
	_ = screen.c.CloseNow()
	if out := phone.outcome("r1"); out["state"] != "failed" || out["message"] != "The TV disconnected" {
		t.Fatalf("%v", out)
	}
	again := e.screen("utb_tv-token", "")
	again.none(ofType("command"), 150*time.Millisecond)
}

func TestSecondSocketOfADeviceReplacesTheFirst(t *testing.T) {
	e := newEnv(t, nil, nil)
	first, _ := twoDevices(t, e)
	second := e.screen("utb_tv-token", "")
	if code := first.closedWith(); code != "replaced" {
		t.Fatalf("code %q", code)
	}
	if n := e.hub.Connections(); n != 2 {
		t.Fatalf("connections %d", n)
	}
	_ = second
}

// --- several clients --------------------------------------------------------------------------------------------

func TestEveryDeviceOfTheUserSeesHeardOutcomeAndReply(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	e.py.add("utb_tablet-token", "owner", "dev-tablet", "Tablet")
	tablet := e.controller("utb_tablet-token", "")
	e.py.add("utb_other-token", "stranger", "dev-x", "Other TV")
	stranger := e.screen("utb_other-token", "")

	phone.send(map[string]any{"t": "say", "id": "a1", "text": "pause"})
	cmd := screen.expect("command")
	screen.ack(cmd["id"].(string), "done")
	for _, d := range []*tc{phone, tablet, screen} {
		if d != screen { // the screen read its heard frame while waiting for the command
			if h := d.next(func(f map[string]any) bool { return f["t"] == "heard" && f["id"] == "a1" }); h["tool"] != "pause" {
				t.Fatalf("heard %v", h)
			}
		}
		if o := d.outcome("a1"); o["state"] != "ok" {
			t.Fatalf("outcome %v", o)
		}
	}
	stranger.none(func(f map[string]any) bool { return f["t"] == "heard" || f["t"] == "outcome" || f["t"] == "command" }, 100*time.Millisecond)
}

func TestFocusStoreKeepsTheLatestAndTellsPeers(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	screen.send(playing(5, "v2", true))
	peers := phone.next(func(f map[string]any) bool {
		if f["t"] != "peers" {
			return false
		}
		for _, p := range f["peers"].([]any) {
			focus, _ := p.(map[string]any)["focus"].(map[string]any)
			if focus != nil && focus["video"].(map[string]any)["id"] == "v2" {
				return true
			}
		}
		return false
	})
	_ = peers
	// An older report (lower seq) is ignored; a position-only change is not announced.
	screen.send(playing(4, "v1", true))
	screen.sync()
	screen.send(map[string]any{"t": "focus", "seq": 6, "screen": "player", "video": map[string]any{"id": "v2", "duration_s": 3600}, "position_s": 500, "playing": true, "rate": 1})
	screen.sync()
	phone.none(ofType("peers"), 100*time.Millisecond)
	phone.send(map[string]any{"t": "say", "id": "f1", "text": "go to 3000 seconds"})
	if cmd := screen.expect("command"); cmd["tool"] != "seek" {
		t.Fatalf("%v", cmd)
	}
}

func TestOnlyAScreenReportsFocusAndOnlyAControllerSpeaks(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	phone.send(playing(1, "v1", true))
	if f := phone.expect("error"); f["code"] != "not_screen" {
		t.Fatal(f)
	}
	screen.send(map[string]any{"t": "say", "id": "z", "text": "pause"})
	if f := screen.expect("error"); f["code"] != "not_controller" {
		t.Fatal(f)
	}
	screen.send(map[string]any{"t": "focus", "seq": 9, "screen": "kitchen"})
	if f := screen.expect("error"); f["code"] != "bad_frame" {
		t.Fatal(f)
	}
}

// --- target choice ----------------------------------------------------------------------------------------------

type twoScreens struct {
	living, bedroom, phone *tc
}

func twoScreenSetup(t *testing.T, e *env, livingPlaying, bedroomPlaying bool) twoScreens {
	t.Helper()
	e.py.add("utb_living", "owner", "dev-living", "Living room")
	e.py.add("utb_bedroom", "owner", "dev-bedroom", "Bedroom")
	e.py.add("utb_phone-token", "owner", "dev-phone", "Phone")
	s := twoScreens{living: e.screen("utb_living", ""), bedroom: e.screen("utb_bedroom", "")}
	s.living.send(playing(1, "v1", livingPlaying))
	s.bedroom.send(playing(1, "v2", bedroomPlaying))
	s.living.sync()
	s.bedroom.sync()
	s.phone = e.controller("utb_phone-token", "")
	return s
}

func TestTheScreenThatPlaysIsTheTarget(t *testing.T) {
	e := newEnv(t, nil, nil)
	s := twoScreenSetup(t, e, false, true)
	s.phone.send(map[string]any{"t": "say", "id": "t1", "text": "pause"})
	if cmd := s.bedroom.expect("command"); cmd["tool"] != "pause" {
		t.Fatal(cmd)
	}
	s.living.none(ofType("command"), 50*time.Millisecond)
}

func TestTheMostRecentFocusIsTheTargetWhenNothingPlays(t *testing.T) {
	e := newEnv(t, nil, nil)
	s := twoScreenSetup(t, e, false, false)
	s.living.send(playing(2, "v9", false))
	s.living.sync()
	s.phone.send(map[string]any{"t": "say", "id": "t1", "text": "play"})
	s.living.expect("command")
}

func TestTwoPlayingScreensAskAndAnAnswerPicksOne(t *testing.T) {
	e := newEnv(t, nil, nil)
	s := twoScreenSetup(t, e, true, true)
	s.phone.send(map[string]any{"t": "say", "id": "t1", "text": "pause"})
	ask := s.phone.expect("ask")
	options := ask["options"].([]any)
	if len(options) != 2 || !strings.Contains(ask["text"].(string), "or") {
		t.Fatalf("ask %v", ask)
	}
	s.living.none(ofType("command"), 50*time.Millisecond)
	// Any device may answer, by frame or by words: here the bedroom by the frame.
	s.phone.send(map[string]any{"t": "answer", "id": ask["id"], "option": "Bedroom"})
	if cmd := s.bedroom.expect("command"); cmd["tool"] != "pause" {
		t.Fatal(cmd)
	}
	s.living.none(ofType("command"), 50*time.Millisecond)
}

func TestASpokenAnswerNamesTheScreen(t *testing.T) {
	e := newEnv(t, nil, nil)
	s := twoScreenSetup(t, e, true, true)
	s.phone.send(map[string]any{"t": "say", "id": "t1", "text": "pause"})
	s.phone.expect("ask")
	s.phone.send(map[string]any{"t": "say", "id": "t2", "text": "the living room"})
	if cmd := s.living.expect("command"); cmd["tool"] != "pause" {
		t.Fatal(cmd)
	}
}

func TestAnUnrelatedUtteranceDropsTheQuestion(t *testing.T) {
	e := newEnv(t, nil, nil)
	s := twoScreenSetup(t, e, true, true)
	s.phone.send(map[string]any{"t": "say", "id": "t1", "text": "pause"})
	s.phone.expect("ask")
	s.phone.send(map[string]any{"t": "say", "id": "t2", "text": "cancel"})
	if out := s.phone.outcome("t2"); out["state"] != "cancelled" {
		t.Fatal(out)
	}
	s.phone.send(map[string]any{"t": "say", "id": "t3", "text": "bedroom"})
	s.phone.expect("reply")
	s.bedroom.none(ofType("command"), 50*time.Millisecond)
}

func TestAPinnedTargetAndToolLists(t *testing.T) {
	e := newEnv(t, nil, nil)
	s := twoScreenSetup(t, e, true, true)
	s.phone.send(map[string]any{"t": "say", "id": "p1", "text": "pause", "target": "dev-living"})
	s.living.expect("command")
	s.phone.send(map[string]any{"t": "say", "id": "p2", "text": "pause", "target": "dev-nowhere"})
	if r := s.phone.expect("reply"); r["text"] != "That screen is not connected" {
		t.Fatal(r)
	}

	// A screen only receives tools it listed in hello.
	e.py.add("utb_kiosk", "owner", "dev-kiosk", "Kiosk")
	kiosk, _ := e.connect("utb_kiosk", helloOpts{roles: []string{"screen"}, tools: []string{"play"}, name: "Kiosk"})
	kiosk.send(playing(1, "v3", false))
	kiosk.sync()
	s.phone.send(map[string]any{"t": "say", "id": "p3", "text": "pause", "target": "dev-kiosk"})
	if r := s.phone.expect("reply"); r["text"] != "Kiosk cannot do that" {
		t.Fatal(r)
	}
	kiosk.none(ofType("command"), 50*time.Millisecond)
}

// --- confirmation -----------------------------------------------------------------------------------------------

func researchUnderstander(text string, _ *proto.Focus) intent.Decision {
	if text == "research this" {
		return intent.Decision{Tool: intent.Research, Args: map[string]any{"question": "what is this"}}
	}
	return intent.Stage1(text)
}

func TestConfirmationIsDecidedByTheServerAndAnsweredByWords(t *testing.T) {
	e := newEnv(t, nil, researchUnderstander)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "k1", "text": "research this"})
	cmd := screen.expect("command")
	confirm, _ := cmd["confirm"].(map[string]any)
	if confirm == nil || confirm["text"] != "Start research?" {
		t.Fatalf("confirm %v", cmd["confirm"])
	}
	id := cmd["id"].(string)
	screen.ack(id, "received")
	screen.ack(id, "confirm_shown")
	screen.sync()
	phone.send(map[string]any{"t": "say", "id": "k2", "text": "yes"})
	ans := screen.expect("answer")
	if ans["id"] != id || ans["option"] != "yes" {
		t.Fatalf("answer %v", ans)
	}
	screen.ack(id, "started")
	if out := phone.outcome("k1"); out["state"] != "ok" {
		t.Fatalf("%v", out)
	}
}

func TestConfirmationNotAnsweredCancels(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.ConfirmWindow = 150 * time.Millisecond }, researchUnderstander)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "k1", "text": "research this"})
	cmd := screen.expect("command")
	id := cmd["id"].(string)
	screen.ack(id, "received")
	screen.ack(id, "confirm_shown")
	out := phone.outcome("k1")
	if out["state"] != "cancelled" || out["message"] != "No answer, cancelled" {
		t.Fatalf("%v", out)
	}
	if rev := screen.expect("revoke"); rev["id"] != id {
		t.Fatal(rev)
	}
}

func TestANoAnswerGoesToTheScreen(t *testing.T) {
	e := newEnv(t, nil, researchUnderstander)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "k1", "text": "research this"})
	id := screen.expect("command")["id"].(string)
	screen.ack(id, "confirm_shown")
	screen.sync()
	phone.send(map[string]any{"t": "answer", "id": id, "option": "no"})
	if ans := screen.expect("answer"); ans["option"] != "no" {
		t.Fatal(ans)
	}
	screen.send(map[string]any{"t": "ack", "id": id, "state": "refused", "message": "Cancelled"})
	if out := phone.outcome("k1"); out["state"] != "refused" {
		t.Fatal(out)
	}
}

// --- limits -----------------------------------------------------------------------------------------------------

func TestConnectionLimitPerUser(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.MaxConnsPerUser = 2 }, nil)
	e.py.add("utb_a", "owner", "da", "A")
	e.py.add("utb_b", "owner", "db", "B")
	e.py.add("utb_c", "owner", "dc", "C")
	e.py.add("utb_z", "someone", "dz", "Z")
	e.controller("utb_a", "")
	e.controller("utb_b", "")
	d, _ := e.rawDial(nil)
	d.send(map[string]any{"t": "hello", "v": 1, "token": "utb_c", "roles": []string{"controller"}})
	if got := d.closedWith(); got != "too_many" {
		t.Fatalf("code %q", got)
	}
	e.controller("utb_z", "") // another user is not affected
}

func TestUtteranceRateLimit(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.UtterancesPerMin = 3 }, nil)
	screen, phone := twoDevices(t, e)
	for i := 0; i < 3; i++ {
		phone.send(map[string]any{"t": "say", "id": fmt.Sprintf("r%d", i), "text": "pause"})
		cmd := screen.expect("command")
		screen.ack(cmd["id"].(string), "done")
		phone.outcome(fmt.Sprintf("r%d", i))
	}
	phone.send(map[string]any{"t": "say", "id": "r3", "text": "pause"})
	if f := phone.expect("error"); f["code"] != "rate_limited" {
		t.Fatal(f)
	}
	screen.none(ofType("command"), 50*time.Millisecond)
}

func TestListenLimitsAndNoSpeechEngine(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.MaxUtteranceBytes = 1000; c.AudioSecondsPerDay = 1 }, nil)
	_, phone := twoDevices(t, e)

	phone.send(map[string]any{"t": "listen", "id": "l1", "state": "start", "format": "audio/wav"})
	if h := phone.expect("heard"); h["state"] != "listening" {
		t.Fatal(h)
	}
	phone.send(map[string]any{"t": "listen", "id": "l2", "state": "start"})
	if f := phone.expect("error"); f["code"] != "busy" {
		t.Fatalf("one utterance at a time: %v", f)
	}
	phone.sendBinary(make([]byte, 600))
	phone.sendBinary(make([]byte, 600))
	if f := phone.expect("error"); f["code"] != "too_long" {
		t.Fatalf("size limit: %v", f)
	}
	phone.send(map[string]any{"t": "listen", "id": "l3", "state": "start"})
	phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["id"] == "l3" && f["state"] == "listening" })
	phone.sendBinary(make([]byte, 100))
	time.Sleep(1100 * time.Millisecond)
	phone.send(map[string]any{"t": "listen", "id": "l3", "state": "end"})
	h := phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["id"] == "l3" && f["state"] == "failed" })
	if h["message"] != "Speech is not available on this server" {
		t.Fatalf("heard %v", h)
	}
	// The one second a day is used up.
	phone.send(map[string]any{"t": "listen", "id": "l4", "state": "start"})
	if f := phone.expect("error"); f["code"] != "daily_audio_limit" {
		t.Fatal(f)
	}
	phone.sendBinary([]byte("x"))
	if f := phone.expect("error"); f["code"] != "no_listen" {
		t.Fatal(f)
	}
}

func TestBinaryFramesNeverReachTheDisk(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("TMPDIR", dir)
	cwd, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = os.Chdir(cwd) }()
	e := newEnv(t, nil, nil)
	_, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "listen", "id": "l1", "state": "start"})
	phone.sendBinary(make([]byte, 4096))
	phone.send(map[string]any{"t": "listen", "id": "l1", "state": "end"})
	phone.next(func(f map[string]any) bool { return f["t"] == "heard" && f["state"] == "failed" })
	entries, _ := os.ReadDir(dir)
	if len(entries) != 0 {
		t.Fatalf("the server wrote %d entries", len(entries))
	}
}

func TestOversizedFrameClosesTheSocket(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.MaxFrameBytes = 2048 }, nil)
	_, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "big", "text": strings.Repeat("a", 4096)})
	if err := <-phone.err; err == nil {
		t.Fatal("expected a close")
	}
}

func TestLongTextIsRefused(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.MaxTextChars = 20 }, nil)
	_, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "say", "id": "t", "text": strings.Repeat("a", 21)})
	if f := phone.expect("error"); f["code"] != "too_long" {
		t.Fatal(f)
	}
}

// --- revocation, origin, idle ------------------------------------------------------------------------------------

func TestARevokedDeviceIsOutWithinTheCacheWindow(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AuthCache = 200 * time.Millisecond }, nil)
	_, phone := twoDevices(t, e)
	e.py.edit("utb_phone-token", func(m *fakeMe) { m.revoked = true })
	if code := phone.closedWith(); code != "revoked" {
		t.Fatalf("code %q", code)
	}
}

func TestSwitchingVoiceOffEndsTheSocket(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AuthCache = 200 * time.Millisecond }, nil)
	screen, _ := twoDevices(t, e)
	e.py.edit("utb_tv-token", func(m *fakeMe) { m.on = false })
	if code := screen.closedWith(); code != "voice_off" {
		t.Fatalf("code %q", code)
	}
}

func TestAnUnreachableBackendKeepsTheSockets(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AuthCache = 100 * time.Millisecond }, nil)
	screen, phone := twoDevices(t, e)
	e.py.mu.Lock()
	e.py.down = true
	e.py.mu.Unlock()
	time.Sleep(400 * time.Millisecond)
	phone.send(map[string]any{"t": "say", "id": "d1", "text": "pause"})
	cmd := screen.expect("command")
	screen.ack(cmd["id"].(string), "done")
	if out := phone.outcome("d1"); out["state"] != "ok" {
		t.Fatal(out)
	}
}

func TestTheTokenCheckIsCached(t *testing.T) {
	e := newEnv(t, nil, nil)
	e.py.add("utb_t", "owner", "d", "TV")
	for i := 0; i < 5; i++ {
		e.screen("utb_t", "")
	}
	e.py.mu.Lock()
	calls := e.py.meCalls
	e.py.mu.Unlock()
	if calls != 1 {
		t.Fatalf("the backend was asked %d times", calls)
	}
}

func TestOriginAllowList(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.Origins = []string{"utubot.example.com"} }, nil)
	if _, err := e.rawDial(http.Header{"Origin": []string{"https://evil.example.org"}}); err == nil {
		t.Fatal("a foreign origin must be refused")
	}
	if _, err := e.rawDial(http.Header{"Origin": []string{"https://utubot.example.com"}}); err != nil {
		t.Fatalf("the allowed origin: %v", err)
	}
	if _, err := e.rawDial(nil); err != nil {
		t.Fatalf("native clients send no origin: %v", err)
	}
}

func TestPingAnswersAndSilentSocketsAreDropped(t *testing.T) {
	e := newEnv(t, func(c *config.Config) {
		c.IdleTimeout = 300 * time.Millisecond
		c.PingInterval = 100 * time.Millisecond
	}, nil)
	e.py.add("utb_t", "owner", "d", "TV")
	d, _ := e.connect("utb_t", helloOpts{roles: []string{"screen"}})
	d.send(map[string]any{"t": "ping", "ts": 42})
	if p := d.expect("pong"); p["ts"].(float64) != 42 {
		t.Fatal(p)
	}
	srvPing := d.expect("ping")
	if srvPing["ts"] == nil {
		t.Fatal(srvPing)
	}
	if code := d.closedWith(); code != "idle_timeout" {
		t.Fatalf("code %q", code)
	}
}

func TestUnknownFramesAreIgnored(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	phone.send(map[string]any{"t": "teleport", "x": 1})
	phone.send(map[string]any{"x": 1})
	phone.send(map[string]any{"t": "say", "id": "u", "text": "pause", "future_field": []int{1}})
	screen.expect("command")
}

// --- statistics --------------------------------------------------------------------------------------------------

func TestStatsRoute(t *testing.T) {
	e := newEnv(t, nil, nil)
	screen, phone := twoDevices(t, e)
	for i := 0; i < 3; i++ {
		id := fmt.Sprintf("st%d", i)
		phone.send(map[string]any{"t": "say", "id": id, "text": "pause"})
		cmd := screen.expect("command")
		screen.ack(cmd["id"].(string), "received")
		screen.ack(cmd["id"].(string), "done")
		phone.outcome(id)
	}
	get := func(token string) (int, string) {
		req, _ := http.NewRequest("GET", e.http.URL+e.cfg.Path+"/v1/stats", nil)
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)
		return resp.StatusCode, string(body)
	}
	if code, _ := get(""); code != 401 {
		t.Fatalf("no token: %d", code)
	}
	if code, _ := get("wrong"); code != 401 {
		t.Fatalf("wrong token: %d", code)
	}
	code, body := get("admin-secret")
	if code != 200 || !strings.Contains(body, `"count":3`) || !strings.Contains(body, `"player"`) || !strings.Contains(body, `"p99_ms"`) {
		t.Fatalf("%d %s", code, body)
	}
	resp, _ := http.Get(e.http.URL + e.cfg.Path + "/v1/health")
	hb, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if !strings.Contains(string(hb), `"ok":true`) || strings.Contains(string(hb), "connections") {
		t.Fatalf("health %s", hb)
	}
}

func TestStatsAreOffWithoutAnAdminToken(t *testing.T) {
	e := newEnv(t, func(c *config.Config) { c.AdminToken = "" }, nil)
	resp, err := http.Get(e.http.URL + e.cfg.Path + "/v1/stats")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 404 {
		t.Fatalf("status %d", resp.StatusCode)
	}
}
