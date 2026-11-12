# Marks, hiding and topics (policy)

Every card in a row is triaged by the backend and gets a verdict for the signed-in user: nothing, a **mark** (a short coloured label
on the card) or **hide** (the card is removed). The verdict is computed from shared per-video analysis plus that user's
**policy**, so two people on the same server see different results.

## What is measured

- **clickbait** (0 to 1): the title withholds, exaggerates or misleads.
- **low_quality** (0 to 1): likely low-effort, AI-narration slop, spam or filler.
- **topics**: which of your listed topics the video clearly belongs to (matched case-insensitively against your exact entries).
- **inflation**: for videos worth a second look (those with a question title or a clickbait score above
  `assess.tier2_clickbait_threshold`), the transcript is analysed for how much of the video carries unique information. A 12
  minute video with 2 useful minutes is labelled `Inflated · 12m≈2m`. Limited per user per day by `assess.tier2_daily_cap_per_user` (30), and only while YouTube is not limiting the server.
- **title question**: the question the title asks, answered from the transcript when known; shown as "AI answer" in the video menu.

## Policy fields

Set them in `[default_policy]` (everyone), per user in `[users.policy]`, or at runtime by the user in the web UI (*Filters*, *Prompts*,
*Models*, *Captions*, *TVs*) or the API (`PUT /v1/me/settings`, `PUT /v1/me/policy`; admins: `PUT /v1/users/{name}/settings`,
`PUT /v1/admin/users/{name}/policy`); runtime changes are stored as per-user overrides, one row per user, and the highest layer wins:
override, then `[users.policy]`, then `[default_policy]`, then the built-in default. See
[Per-user settings](server.md#per-user-settings) for the whole settings document and what an unset field follows.

| Field | Default | Meaning |
|---|---|---|
| `language` | `"en"` | language for summaries (`{language}` in prompts) and transcripts |
| `hide_topics` | `[]` | videos matching any entry are hidden |
| `mark_topics` | `[]` | videos matching an entry get a mark with the topic name |
| `hide_clickbait_above` | `0.9` | clickbait score at or above this hides the card |
| `mark_clickbait_above` | `0.6` | at or above this adds the "Clickbait" mark |
| `hide_low_quality_above` | `0.9` | low quality score at or above this hides |
| `mark_low_quality_above` | `0.65` | at or above this adds the "Low quality" mark |
| `mark_inflated_ratio_below` | `0.35` | essential/total ratio at or below this marks "Inflated" |
| `inflated_min_duration_s` | `300` | videos shorter than this are never marked inflated |
| `answer_in_label` | `false` | append the short answer to the mark text |
| `auto_long` | unset | `true`/`false` overrides `[summary] auto_long` (generate the long summary in the background after a side-panel summary); unset follows the config |
| `mark_only` | unset | `true`: the TV shows cards that would be hidden with a mark instead; unset follows `[setup.defaults] mark_only` |
| `models` | `{}` | per-task model (`glance`, `summary`, `answer`, `triage`, `analysis`); a task without an entry follows `[llm.<task>]` |
| `auto_transcribe` | `"on_open"` | `off`, `on_open` or `on_dwell`: when a video without captions is transcribed without asking. `on_open`: when you open the video (Summary view, insight, answer); `on_dwell`: also while you merely linger on it (the side panel). `off`: always ask first. See [captions.md](captions.md#transcripts-for-videos-without-captions) |
| `auto_transcribe_max_minutes` | `30` | videos longer than this (or of unknown length) are not transcribed automatically: they answer `needs_transcript` and the TV asks |
| `summary_delay_ms` | `700` | TV: how long a card stays focused before its summary is requested |
| `summary_panel` | unset | TV: side panel on by default; unset follows `[setup.defaults] summary_panel` |
| `auto_captions` | unset | TV: offer u·tubot captions automatically; unset follows `[setup.defaults] auto_captions` |
| `update_checks` | `true` | TV: ask the server for newer app versions |

Thresholds accept 0 to 1.01 (at most 50 topics of at most 80 characters each; blanks and duplicates are dropped). Hiding wins over
marking. Raise a threshold to see fewer marks; set a hide threshold to `1.01` to never hide on that score.
Topics work best as short, concrete phrases (`"reaction videos"`, `"celebrity gossip"`), because the model must pick them from your
list verbatim.

```toml
[default_policy]
hide_topics = ["AI-generated narration slop"]

[[users]]
name = "owner"
admin = true
[users.policy]
mark_topics = ["celebrity gossip"]
mark_clickbait_above = 0.5
```

Changing topics re-evaluates videos for that user; the shared title analysis is cached for `assess.triage_cache_ttl_s`.

## Mark only

In the app, *Settings, u·tubot, Mark only, never hide* keeps videos that policy would hide and shows them with a mark instead. The
server's setup can ship the default (`[setup.defaults] mark_only = true`), and the web UI keeps a per-user choice (`mark_only` above;
the TV reads it in a later release). When the backend is unreachable or too slow, the app shows
videos unfiltered: a verdict never blocks a row longer than the wait cap (`assess.wait_ms_cap`, 3 s) plus a little network slack.

## Feedback

`POST /v1/feedback` stores "this mark was wrong or right" reports for later threshold tuning; nothing is applied automatically.
