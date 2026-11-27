// Package intent holds the command model's fixed tool list (plan 2.8), argument validation, the confirmation rule
// and the stage 1 phrase matcher. No model is involved in this checkpoint.
package intent

import (
	"fmt"
	"math"
	"sort"
	"strings"

	"github.com/evrenesat/u-tubot/realtime/internal/proto"
)

// Tool names.
const (
	Play         = "play"
	Pause        = "pause"
	Seek         = "seek"
	NextPart     = "next_part"
	PreviousPart = "previous_part"
	CutOff       = "cut_off"
	CutOn        = "cut_on"
	CutPreset    = "cut_preset"
	CutCustom    = "cut_custom"
	CaptionsHQ   = "captions_hq"
	Summary      = "summary"
	Research     = "research"
	AskVideo     = "ask_video"
	ShowMore     = "show_more"
	CloseView    = "close_view"
	Scroll       = "scroll"
	Cancel       = "cancel"
	Clarify      = "clarify"
	None         = "none"
)

// Families group the tools for the statistics.
const (
	FamilyPlayer  = "player"
	FamilyCut     = "cut"
	FamilyCaption = "captions"
	FamilyView    = "view"
	FamilyAsk     = "ask"
	FamilyOther   = "other"
)

// Limits of arguments.
const (
	MaxPromptChars   = 2000
	MaxQuestionChars = 2000
	MaxOptions       = 4
	MaxSeekBySeconds = 24 * 60 * 60
	// LongVideoSeconds is the length over which HQ captions ask first (plan 2.8: 30 minutes).
	LongVideoSeconds = 30 * 60
	ModeWatched      = "watched"
)

// Spec describes one tool.
type Spec struct {
	Name string
	// Family is the statistics group.
	Family string
	// NeedsVideo tools answer "Focus a video first" without a focused video.
	NeedsVideo bool
	// Local tools are answered by the server itself and never sent to a screen.
	Local bool
}

var specs = map[string]Spec{
	Play:         {Name: Play, Family: FamilyPlayer, NeedsVideo: true},
	Pause:        {Name: Pause, Family: FamilyPlayer, NeedsVideo: true},
	Seek:         {Name: Seek, Family: FamilyPlayer, NeedsVideo: true},
	NextPart:     {Name: NextPart, Family: FamilyPlayer, NeedsVideo: true},
	PreviousPart: {Name: PreviousPart, Family: FamilyPlayer, NeedsVideo: true},
	CutOff:       {Name: CutOff, Family: FamilyCut, NeedsVideo: true},
	CutOn:        {Name: CutOn, Family: FamilyCut, NeedsVideo: true},
	CutPreset:    {Name: CutPreset, Family: FamilyCut, NeedsVideo: true},
	CutCustom:    {Name: CutCustom, Family: FamilyCut, NeedsVideo: true},
	CaptionsHQ:   {Name: CaptionsHQ, Family: FamilyCaption, NeedsVideo: true},
	Summary:      {Name: Summary, Family: FamilyView, NeedsVideo: true},
	Research:     {Name: Research, Family: FamilyView, NeedsVideo: true},
	AskVideo:     {Name: AskVideo, Family: FamilyAsk, NeedsVideo: true},
	ShowMore:     {Name: ShowMore, Family: FamilyView},
	CloseView:    {Name: CloseView, Family: FamilyView},
	Scroll:       {Name: Scroll, Family: FamilyView},
	Cancel:       {Name: Cancel, Family: FamilyOther},
	Clarify:      {Name: Clarify, Family: FamilyOther, Local: true},
	None:         {Name: None, Family: FamilyOther, Local: true},
}

// Lookup returns the spec of a tool.
func Lookup(name string) (Spec, bool) {
	s, ok := specs[name]
	return s, ok
}

// Names lists every tool.
func Names() []string {
	out := make([]string, 0, len(specs))
	for n := range specs {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}

// Family returns the statistics family of a tool ("other" for an unknown one).
func Family(name string) string {
	if s, ok := specs[name]; ok {
		return s.Family
	}
	return FamilyOther
}

// Decision is what an understanding stage returns.
type Decision struct {
	Tool    string
	Args    map[string]any
	Say     string
	Options []string
}

// Fault is a validation failure with a sentence for the user.
type Fault struct{ Message string }

func (f *Fault) Error() string { return f.Message }

func fault(format string, a ...any) error { return &Fault{Message: fmt.Sprintf(format, a...)} }

// Validate checks a decision's arguments against the tool's schema and the focus, and returns the cleaned arguments.
func Validate(d Decision, focus *proto.Focus) (map[string]any, error) {
	spec, ok := specs[d.Tool]
	if !ok {
		return nil, fault("I did not understand that")
	}
	if spec.NeedsVideo && (focus == nil || focus.Video == nil) {
		return nil, fault("Focus a video first")
	}
	args := d.Args
	if args == nil {
		args = map[string]any{}
	}
	switch d.Tool {
	case Seek:
		return validateSeek(args, focus)
	case Scroll:
		dir, _ := args["direction"].(string)
		if dir == "" {
			dir = "down"
		}
		if dir != "up" && dir != "down" {
			return nil, fault("Scroll up or down")
		}
		return map[string]any{"direction": dir}, nil
	case CutCustom:
		prompt, _ := args["prompt"].(string)
		prompt = strings.TrimSpace(prompt)
		if prompt == "" || len([]rune(prompt)) > MaxPromptChars {
			return nil, fault("Describe the cut in up to %d characters", MaxPromptChars)
		}
		out := map[string]any{"prompt": prompt}
		return withMode(out, args)
	case CutPreset:
		id, _ := args["preset_id"].(string)
		if id == "" {
			return nil, fault("Which cut?")
		}
		return withMode(map[string]any{"preset_id": id}, args)
	case AskVideo:
		q, _ := args["question"].(string)
		q = strings.TrimSpace(q)
		if q == "" || len([]rune(q)) > MaxQuestionChars {
			return nil, fault("Ask a question of up to %d characters", MaxQuestionChars)
		}
		return map[string]any{"question": q}, nil
	case CaptionsHQ:
		out := map[string]any{}
		if f, ok := args["force"].(bool); ok && f {
			out["force"] = true
		}
		return out, nil
	case Summary:
		out := map[string]any{}
		if k, _ := args["prompt_key"].(string); k != "" {
			out["prompt_key"] = k
		}
		return out, nil
	case Research:
		out := map[string]any{}
		if k, _ := args["kind"].(string); k != "" {
			out["kind"] = k
		}
		if q, _ := args["question"].(string); q != "" {
			out["question"] = q
		}
		if len(out) == 0 {
			return nil, fault("What should I research?")
		}
		return out, nil
	case Clarify:
		text, _ := args["text"].(string)
		if text == "" {
			return nil, fault("I did not understand that")
		}
		return map[string]any{"text": text}, nil
	case None:
		say, _ := args["say"].(string)
		return map[string]any{"say": say}, nil
	}
	return map[string]any{}, nil
}

func withMode(out, args map[string]any) (map[string]any, error) {
	if mode, ok := args["mode"].(string); ok && mode != "" {
		out["mode"] = mode
	}
	return out, nil
}

func validateSeek(args map[string]any, focus *proto.Focus) (map[string]any, error) {
	to, hasTo := numArg(args["to_s"])
	by, hasBy := numArg(args["by_s"])
	if hasTo == hasBy {
		return nil, fault("Say where to go, for example back 30 seconds")
	}
	if hasTo {
		if to < 0 {
			return nil, fault("That is before the start of the video")
		}
		if d := focus.Video.DurationS; d > 0 && to > d {
			return nil, fault("That is past the end of the video")
		}
		return map[string]any{"to_s": to}, nil
	}
	if math.Abs(by) > MaxSeekBySeconds {
		return nil, fault("That is too far to skip")
	}
	return map[string]any{"by_s": by}, nil
}

func numArg(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, !math.IsNaN(n) && !math.IsInf(n, 0)
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	}
	return 0, false
}

// Confirm decides, from the tool table and the focus and never from a model, whether a command needs an OK first.
// It returns the text to show and an estimate in seconds (0: none).
func Confirm(tool string, args map[string]any, focus *proto.Focus) (text string, etaS int, needed bool) {
	switch tool {
	case CutPreset, CutCustom:
		if mode, _ := args["mode"].(string); mode == ModeWatched {
			return "Start a watched cut?", 0, true
		}
	case Research:
		return "Start research?", 0, true
	case CaptionsHQ:
		if focus != nil && focus.Video != nil && focus.Video.DurationS > LongVideoSeconds {
			return fmt.Sprintf("Make HQ subtitles for this %d minute video?", int(focus.Video.DurationS/60)), 0, true
		}
	}
	return "", 0, false
}
