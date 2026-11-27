package intent

import (
	"errors"
	"testing"

	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

func TestStage1Phrases(t *testing.T) {
	cases := map[string]string{
		"Pause": Pause, "pause the video, please": Pause, "Hey, stop!": Pause, "Play.": Play, "resume": Play,
		"next part": NextPart, "go to the next part": NextPart, "previous chapter": PreviousPart,
		"cut off": CutOff, "turn the cut off": CutOff, "turn off the cut": CutOff, "cuts on": CutOn, "switch the cut on": CutOn,
		"play the full video": CutOff, "show more": ShowMore, "close that": CloseView, "never mind": Cancel, "Cancel": Cancel,
	}
	for text, want := range cases {
		if got := Stage1(text).Tool; got != want {
			t.Errorf("%q: got %q want %q", text, got, want)
		}
	}
}

func TestStage1Seek(t *testing.T) {
	type want struct {
		key string
		val float64
	}
	cases := map[string]want{
		"back 30 seconds":                    {"by_s", -30},
		"go back thirty seconds":             {"by_s", -30},
		"rewind a minute":                    {"by_s", -60},
		"rewind 30":                          {"by_s", -30},
		"skip ahead two minutes":             {"by_s", 120},
		"forward 10 seconds please":          {"by_s", 10},
		"skip 45 seconds":                    {"by_s", 45},
		"go forward twenty five seconds":     {"by_s", 25},
		"back one minute and thirty seconds": {"by_s", -90},
		"go to 12 minutes":                   {"to_s", 720},
		"seek to 1:30":                       {"to_s", 90},
		"jump to 1:02:03":                    {"to_s", 3723},
		"go to one hour":                     {"to_s", 3600},
		"restart":                            {"to_s", 0},
		"from the beginning":                 {"to_s", 0},
	}
	for text, w := range cases {
		d := Stage1(text)
		if d.Tool != Seek {
			t.Errorf("%q: tool %q", text, d.Tool)
			continue
		}
		got, ok := d.Args[w.key].(float64)
		if !ok || got != w.val {
			t.Errorf("%q: args %v want %s=%v", text, d.Args, w.key, w.val)
		}
	}
}

func TestStage1LeavesOpenCommandsToStage2(t *testing.T) {
	for _, text := range []string{"", "make a cut that keeps only the benchmarks", "what is this video about", "back", "go to", "skip", "back soon", "go back to the future", "play the guitar solo"} {
		if d := Stage1(text); d.Tool != "" {
			t.Errorf("%q matched %q", text, d.Tool)
		}
	}
}

func TestYesNoAndOptions(t *testing.T) {
	if YesNo("Yes please") != 1 || YesNo("ok") != 1 || YesNo("nope") == 1 || YesNo("no") != -1 || YesNo("maybe") != 0 {
		t.Fatal("yes/no")
	}
	opts := []string{"Living room", "Bedroom"}
	cases := map[string]int{"living room": 0, "the bedroom": 1, "bedroom please": 1, "first": 0, "the second": 1, "kitchen": -1, "": -1}
	for text, want := range cases {
		if got := OptionIndex(text, opts); got != want {
			t.Errorf("%q: %d want %d", text, got, want)
		}
	}
}

func focusOf(duration float64) *proto.Focus {
	return &proto.Focus{Video: &proto.Video{ID: "v1", DurationS: duration}}
}

func TestValidate(t *testing.T) {
	cases := []struct {
		name  string
		d     Decision
		focus *proto.Focus
		fault string
	}{
		{"unknown tool", Decision{Tool: "launch_rocket"}, focusOf(60), "I did not understand that"},
		{"video tool without video", Decision{Tool: Pause}, &proto.Focus{}, "Focus a video first"},
		{"video tool without focus", Decision{Tool: Pause}, nil, "Focus a video first"},
		{"seek needs one of", Decision{Tool: Seek, Args: map[string]any{}}, focusOf(60), "Say where to go, for example back 30 seconds"},
		{"seek both", Decision{Tool: Seek, Args: map[string]any{"to_s": 1.0, "by_s": 2.0}}, focusOf(60), "Say where to go, for example back 30 seconds"},
		{"seek past end", Decision{Tool: Seek, Args: map[string]any{"to_s": 90.0}}, focusOf(60), "That is past the end of the video"},
		{"seek negative", Decision{Tool: Seek, Args: map[string]any{"to_s": -1.0}}, focusOf(60), "That is before the start of the video"},
		{"seek too far", Decision{Tool: Seek, Args: map[string]any{"by_s": 1e9}}, focusOf(60), "That is too far to skip"},
		{"custom cut empty", Decision{Tool: CutCustom, Args: map[string]any{"prompt": "  "}}, focusOf(60), "Describe the cut in up to 2000 characters"},
		{"scroll sideways", Decision{Tool: Scroll, Args: map[string]any{"direction": "left"}}, nil, "Scroll up or down"},
	}
	for _, c := range cases {
		_, err := Validate(c.d, c.focus)
		var f *Fault
		if !errors.As(err, &f) || f.Message != c.fault {
			t.Errorf("%s: err %v want %q", c.name, err, c.fault)
		}
	}
	args, err := Validate(Decision{Tool: Seek, Args: map[string]any{"by_s": -30.0}}, focusOf(0))
	if err != nil || args["by_s"] != -30.0 {
		t.Fatalf("%v %v", args, err)
	}
	if _, err := Validate(Decision{Tool: ShowMore}, nil); err != nil {
		t.Fatal("view tools need no video:", err)
	}
}

func TestConfirmRuleLivesInTheTable(t *testing.T) {
	long := focusOf(3600)
	if _, _, ok := Confirm(CutPreset, map[string]any{"mode": ModeWatched}, long); !ok {
		t.Fatal("watched cuts confirm")
	}
	if _, _, ok := Confirm(CutPreset, map[string]any{}, long); ok {
		t.Fatal("quick cuts do not")
	}
	if _, _, ok := Confirm(Research, map[string]any{"kind": "x"}, long); !ok {
		t.Fatal("research confirms")
	}
	if _, _, ok := Confirm(CaptionsHQ, nil, long); !ok {
		t.Fatal("long HQ captions confirm")
	}
	if _, _, ok := Confirm(CaptionsHQ, nil, focusOf(600)); ok {
		t.Fatal("short ones do not")
	}
	if _, _, ok := Confirm(Pause, nil, long); ok {
		t.Fatal("player tools never confirm")
	}
}
