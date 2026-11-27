package intent

import (
	"regexp"
	"strconv"
	"strings"
)

// Stage1 matches normalised phrases and small patterns for the player family, with no model (plan 2.8).
// It returns a decision with an empty Tool when nothing matches.
func Stage1(text string) Decision {
	words := tokens(normalise(text))
	if len(words) == 0 {
		return Decision{}
	}
	phrase := strings.Join(words, " ")
	if tool, ok := phrases[phrase]; ok {
		return Decision{Tool: tool}
	}
	if d, ok := matchCut(phrase); ok {
		return d
	}
	if d, ok := matchSeek(words); ok {
		return d
	}
	return Decision{}
}

// YesNo reads a spoken confirmation: 1 yes, -1 no, 0 neither.
func YesNo(text string) int {
	phrase := strings.Join(tokens(normalise(text)), " ")
	if yes[phrase] {
		return 1
	}
	if no[phrase] {
		return -1
	}
	return 0
}

// OptionIndex finds which option of an ask a spoken answer names: by label (whole or contained) or by ordinal.
func OptionIndex(text string, options []string) int {
	phrase := strings.Join(tokens(normalise(text)), " ")
	if phrase == "" {
		return -1
	}
	for i, o := range options {
		if strings.Join(tokens(normalise(o)), " ") == phrase {
			return i
		}
	}
	found := -1
	for i, o := range options {
		label := strings.Join(tokens(normalise(o)), " ")
		if label != "" && (strings.Contains(phrase, label) || strings.Contains(label, phrase)) {
			if found >= 0 {
				return -1
			}
			found = i
		}
	}
	if found >= 0 {
		return found
	}
	for i, ordinal := range ordinals {
		if (phrase == ordinal || phrase == "the "+ordinal) && i < len(options) {
			return i
		}
	}
	return -1
}

var ordinals = []string{"first", "second", "third", "fourth"}

var phrases = map[string]string{
	"play": Play, "resume": Play, "continue": Play, "unpause": Play, "play it": Play, "start playing": Play,
	"play the video": Play, "resume playing": Play, "keep playing": Play, "carry on": Play,
	"pause": Pause, "stop": Pause, "hold on": Pause, "wait": Pause, "pause it": Pause, "pause the video": Pause,
	"stop the video": Pause, "freeze": Pause,
	"next part": NextPart, "next chapter": NextPart, "next": NextPart, "next section": NextPart, "skip this part": NextPart,
	"skip part": NextPart, "go to the next part": NextPart,
	"previous part": PreviousPart, "last part": PreviousPart, "previous": PreviousPart, "previous chapter": PreviousPart,
	"previous section": PreviousPart, "go back a part": PreviousPart, "go to the previous part": PreviousPart,
	"show more": ShowMore, "more": ShowMore, "tell me more": ShowMore, "read more": ShowMore,
	"close": CloseView, "close that": CloseView, "dismiss": CloseView, "hide that": CloseView, "go away": CloseView,
	"close it": CloseView, "close this": CloseView,
	"cancel": Cancel, "never mind": Cancel, "nevermind": Cancel, "forget it": Cancel, "abort": Cancel,
	"cancel that": Cancel,
	"cut on":      CutOn, "cuts on": CutOn, "cut off": CutOff, "cuts off": CutOff,
	"play the full video": CutOff, "play uncut": CutOff, "play the original": CutOff, "play the whole video": CutOff,
}

var yes = map[string]bool{
	"yes": true, "yeah": true, "yep": true, "ok": true, "okay": true, "sure": true, "do it": true, "go ahead": true,
	"confirm": true, "yes please": true, "correct": true, "start it": true,
}

var no = map[string]bool{
	"no": true, "nope": true, "dont": true, "do not": true, "back": true, "no thanks": true, "negative": true,
}

var cutToggle = regexp.MustCompile(`^(?:turn |switch )?(?:the )?cuts? (on|off)$|^(?:turn |switch )(on|off) (?:the )?cuts?$|^(?:enable|disable) (?:the )?cuts?$`)

func matchCut(phrase string) (Decision, bool) {
	m := cutToggle.FindStringSubmatch(phrase)
	if m == nil {
		return Decision{}, false
	}
	state := m[1] + m[2]
	if state == "" {
		state = "on"
		if strings.HasPrefix(phrase, "disable") {
			state = "off"
		}
	}
	if state == "on" {
		return Decision{Tool: CutOn}, true
	}
	return Decision{Tool: CutOff}, true
}

var fillers = map[string]bool{"please": true, "hey": true, "ok": true, "okay": true, "could": true, "you": true, "can": true, "would": true, "just": true, "now": true, "kindly": true, "um": true, "uh": true}

func normalise(text string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(text) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == ':', r == '.':
			b.WriteRune(r)
		case r == '\'' || r == '’':
		default:
			b.WriteRune(' ')
		}
	}
	return strings.Trim(b.String(), " .")
}

func tokens(s string) []string {
	raw := strings.Fields(s)
	// Strip politeness around the command, never inside it ("ok" alone is an answer, not a filler).
	for len(raw) > 1 && fillers[raw[0]] {
		raw = raw[1:]
	}
	for len(raw) > 1 && fillers[raw[len(raw)-1]] {
		raw = raw[:len(raw)-1]
	}
	for i, w := range raw {
		raw[i] = strings.Trim(w, ".")
	}
	return raw
}

var unitSeconds = map[string]float64{
	"second": 1, "seconds": 1, "sec": 1, "secs": 1,
	"minute": 60, "minutes": 60, "min": 60, "mins": 60,
	"hour": 3600, "hours": 3600,
}

var smallNumbers = map[string]int{
	"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
	"eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
	"eighteen": 18, "nineteen": 19, "a": 1, "an": 1,
}

var tensNumbers = map[string]int{"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

// number reads a count at the start of words: digits, a word below 100 or a tens word with a unit word.
func number(words []string) (value int, used int) {
	if len(words) == 0 {
		return 0, 0
	}
	if n, err := strconv.Atoi(words[0]); err == nil {
		return n, 1
	}
	if t, ok := tensNumbers[words[0]]; ok {
		if len(words) > 1 {
			if s, ok := smallNumbers[words[1]]; ok && s > 0 && s < 10 && words[1] != "a" && words[1] != "an" {
				return t + s, 2
			}
		}
		return t, 1
	}
	if n, ok := smallNumbers[words[0]]; ok {
		return n, 1
	}
	return 0, 0
}

// duration reads "N unit [N unit ...]" and returns the seconds and how many words were used.
func duration(words []string) (seconds float64, used int) {
	for used < len(words) {
		w := words[used:]
		if w[0] == "and" && used > 0 {
			used++
			continue
		}
		n, c := number(w)
		if c == 0 || c >= len(w) {
			break
		}
		mult, ok := unitSeconds[w[c]]
		if !ok {
			break
		}
		seconds += float64(n) * mult
		used += c + 1
	}
	for used > 0 && words[used-1] == "and" {
		used--
	}
	return seconds, used
}

var clock = regexp.MustCompile(`^(\d{1,2}):(\d{2})(?::(\d{2}))?$`)

func clockSeconds(word string) (float64, bool) {
	m := clock.FindStringSubmatch(word)
	if m == nil {
		return 0, false
	}
	a, _ := strconv.Atoi(m[1])
	b, _ := strconv.Atoi(m[2])
	if b >= 60 {
		return 0, false
	}
	if m[3] == "" {
		return float64(a*60 + b), true
	}
	c, _ := strconv.Atoi(m[3])
	if c >= 60 {
		return 0, false
	}
	return float64(a*3600 + b*60 + c), true
}

var startPhrases = map[string]bool{
	"restart": true, "start over": true, "from the beginning": true, "go to the start": true, "go to the beginning": true,
	"play from the start": true, "play from the beginning": true, "back to the start": true, "go back to the start": true,
	"rewind to the start": true, "take it from the top": true,
}

// seekPrefixes lead a seek phrase; the rest is a duration, a bare count of seconds or a clock time.
// A longer prefix wins over a shorter one.
var seekPrefixes = []struct {
	words []string
	sign  float64
	abs   bool
}{
	{[]string{"go", "back"}, -1, false}, {[]string{"skip", "back"}, -1, false}, {[]string{"jump", "back"}, -1, false},
	{[]string{"go", "backward"}, -1, false}, {[]string{"go", "backwards"}, -1, false}, {[]string{"back", "up"}, -1, false},
	{[]string{"rewind"}, -1, false}, {[]string{"back"}, -1, false}, {[]string{"backward"}, -1, false}, {[]string{"backwards"}, -1, false},
	{[]string{"skip", "ahead"}, 1, false}, {[]string{"skip", "forward"}, 1, false}, {[]string{"jump", "ahead"}, 1, false},
	{[]string{"jump", "forward"}, 1, false}, {[]string{"go", "forward"}, 1, false}, {[]string{"move", "forward"}, 1, false},
	{[]string{"move", "ahead"}, 1, false}, {[]string{"fast", "forward"}, 1, false}, {[]string{"forward"}, 1, false},
	{[]string{"forwards"}, 1, false}, {[]string{"ahead"}, 1, false}, {[]string{"advance"}, 1, false}, {[]string{"skip"}, 1, false},
	{[]string{"go", "to"}, 0, true}, {[]string{"seek", "to"}, 0, true}, {[]string{"jump", "to"}, 0, true},
	{[]string{"skip", "to"}, 0, true}, {[]string{"move", "to"}, 0, true}, {[]string{"seek"}, 0, true},
}

func hasPrefix(words, prefix []string) bool {
	if len(words) <= len(prefix) {
		return false
	}
	for i, p := range prefix {
		if words[i] != p {
			return false
		}
	}
	return true
}

func matchSeek(words []string) (Decision, bool) {
	if startPhrases[strings.Join(words, " ")] {
		return Decision{Tool: Seek, Args: map[string]any{"to_s": 0.0}}, true
	}
	best := -1
	for i, p := range seekPrefixes {
		if hasPrefix(words, p.words) && (best < 0 || len(p.words) > len(seekPrefixes[best].words)) {
			best = i
		}
	}
	if best < 0 {
		return Decision{}, false
	}
	p := seekPrefixes[best]
	rest := words[len(p.words):]
	if rest[0] == "by" || rest[0] == "for" {
		rest = rest[1:]
	}
	if len(rest) == 0 {
		return Decision{}, false
	}
	if p.abs {
		if s, ok := clockSeconds(rest[0]); ok && len(rest) == 1 {
			return Decision{Tool: Seek, Args: map[string]any{"to_s": s}}, true
		}
		if s, used := duration(rest); used == len(rest) && used > 0 {
			return Decision{Tool: Seek, Args: map[string]any{"to_s": s}}, true
		}
		return Decision{}, false
	}
	if s, used := duration(rest); used == len(rest) && used > 0 {
		return Decision{Tool: Seek, Args: map[string]any{"by_s": p.sign * s}}, true
	}
	// A bare count means seconds: "rewind 30".
	if n, c := number(rest); c == len(rest) && c > 0 && rest[0] != "a" && rest[0] != "an" {
		return Decision{Tool: Seek, Args: map[string]any{"by_s": p.sign * float64(n)}}, true
	}
	return Decision{}, false
}
