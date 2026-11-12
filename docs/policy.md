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

Set them in `[default_policy]` (everyone), per user in `[users.policy]`, or at runtime in the web UI (admin) or the API
(`PUT /v1/me/policy`, `PUT /v1/admin/users/{name}/policy`); runtime changes are stored as per-user overrides.

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

Hiding wins over marking. Raise a threshold to see fewer marks; set a hide threshold to `1.01` to never hide on that score.
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
server's setup can ship the default (`[setup.defaults] mark_only = true`). When the backend is unreachable or too slow, the app shows
videos unfiltered: a verdict never blocks a row longer than the wait cap (`assess.wait_ms_cap`, 3 s) plus a little network slack.

## Feedback

`POST /v1/feedback` stores "this mark was wrong or right" reports for later threshold tuning; nothing is applied automatically.
