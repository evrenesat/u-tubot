# Prompt sets

Summaries are produced by prompts you choose. A **prompt set** is a JSON file with several prompts. It can be hosted anywhere and
imported by URL, uploaded in the web UI or imported from the TV. Prompts are per user; a built-in set (`builtin`) always exists
(Glance, TL;DR, Answer the title, Key takeaways and more) and cannot be changed.

Two prompts are chosen per user: the **default** (what the Summary view shows, `builtin/tldr` unless you change it) and the
**panel default** (what the side panel shows while you browse, `builtin/glance` unless you change it). See
[Two defaults](#two-defaults-the-summary-view-and-the-side-panel).

## Format

```json
{
  "tubeai_prompt_set": 1,
  "id": "my-prompts",
  "name": "My prompts",
  "version": "2026-11-12",
  "prompts": [
    {
      "id": "tldr",
      "label": "TL;DR",
      "default": true,
      "system": "You summarize YouTube videos for a TV viewer. Reply in {language}.",
      "template": "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\nTranscript:\n{transcript}\n\nGive a 5-bullet TL;DR.",
      "max_tokens": 700,
      "model": null
    }
  ]
}
```

- `tubeai_prompt_set`: format version, must be `1` (the historic key name is kept for compatibility).
- `id` (set): `[A-Za-z0-9._-]`, up to 64 characters, starts with a letter or digit. `name`, `version`: free text.
- Up to 50 prompts per set; each `id` unique within the set. The effective key is `<set id>/<prompt id>`.
- `label`: what the TV shows. `default: true` marks the set's preferred prompt (the user's chosen default decides).
- `system`, `template`: up to 20 000 characters each; `template` is required.
- `max_tokens`: 16 to 8000 (default 700). This is the budget for the visible answer; the backend adds `[llm] reasoning_headroom_tokens`
  (default 2048) on top for reasoning models. A cut-off answer is retried once with double the budget.
- `model`: optional, overrides the summary model: a model name or `provider:model` naming a provider from your config. It wins over the user's own model for the task (web UI, *Models*), which wins over `[llm.<task>]`.
- `task`: optional, `"summary"` (default) or `"glance"`. It picks which `[llm.*]` table runs the prompt: `[llm.summary]`, or
  `[llm.glance]` (the fast model for short panel summaries, falling back to `[llm.summary]` with reasoning off; see
  [llm-providers.md](llm-providers.md)). Files without it keep working unchanged.

### Variables

Written in braces in `system` and `template`; unknown braces are left alone, missing values become empty.

| Variable | Value |
|---|---|
| `{title}` | video title |
| `{channel}` | channel name |
| `{duration}` | length, for example `12m` |
| `{description}` | description, truncated |
| `{transcript}` | transcript text with timestamps like `[00:20]`, shortened to the token budget |
| `{language}` | the user's language from policy (`en`) |
| `{question}` | the question the title poses, as the title triage detected it (empty when the title asks nothing or triage has not run yet), for "answer" style prompts |

Validate a file before hosting it: `uv run utubot prompts validate my-prompts.json`.

## Built-in prompts

| Key | Purpose |
|---|---|
| `builtin/glance` | the side-panel summary, see below |
| `builtin/tldr` | 5 short bullets, the default of the Summary view |
| `builtin/answer-title` | the question or curiosity gap of the title, then the direct answer in 2 to 3 sentences |
| `builtin/takeaways` | 5 to 8 takeaways with `[mm:ss]` timestamps |
| `builtin/worth-it` | Watch, Skim or Skip verdict with reasons |
| `builtin/eli-new` | explanation for a newcomer |

### Glance

The glance summary is what the side panel shows while you browse, so it has to fit on screen and appear fast. It is at most
about 280 characters in at most 3 short lines, plain text, in your language, with no preamble. It runs with a 160 token answer
budget and, by default, reasoning off, on `[llm.glance]` (or `[llm.summary]` when that table is absent).

It looks for the answer first. If the title (or thumbnail text, when the metadata has any) poses or implies a question, or is a
curiosity gap or clickbait ("you won't believe", "this changes everything", "the truth about", "why ...", "what happened", a
number tease, a cliffhanger), line 1 is `→ ` plus the direct, specific answer from the transcript: names, numbers, the actual
reveal. If the transcript does not answer it, the line says so in a few words ("Not answered in the video"). One or two lines
with the gist follow. A title that asks nothing gets just the gist. The question the title triage already detected is passed in
as `{question}` so the model knows exactly what to resolve; the prompt still works when it is empty.

For videos longer than `summary.token_budget`, the glance (like every prompt) reads the condensed transcript, and the condense
step keeps the passage that answers the title's question or reveals its tease in its notes (lines starting `ANSWER:`). Condensed
notes made before this change stay cached; delete rows from the `condensed` table to rebuild them.

The exact text is in `ai-backend/src/utubot/prompts.py` (`GLANCE_SYSTEM`, `GLANCE_TEMPLATE`). `builtin/answer-title` uses the
same curiosity-first logic with a longer answer (2 to 3 sentences, 400 tokens).

## Two defaults: the Summary view and the side panel

| | Used for | Default | Change it with |
|---|---|---|---|
| `default` | the Summary view and any request without `prompt` | `builtin/tldr` | `PUT /v1/prompts/default {"key": ...}`, the TV prompt list, the web UI |
| `panel_default` | the side panel's automatic summaries: `GET /v1/videos/{id}/summary?prompt=panel` | `builtin/glance` (`[summary] panel_prompt`) | `PUT /v1/prompts/panel-default {"key": ...}`, the web UI (*Prompts, Defaults*) |

`GET /v1/prompts` returns both (`default`, `panel_default`) and marks each prompt with `default` and `panel_default`. A user's
own panel choice wins over `[summary] panel_prompt`; if the chosen prompt no longer exists (its set was deleted or refreshed
without it) the config value applies, then `builtin/glance`. Deleting a set that holds either default resets that default.

### Long summaries in the background

`[summary] auto_long = false` by default. When it is `true` (or `auto_long` is `true` in a user's policy, which overrides the
config for that user), each panel request that finishes with a ready summary also queues the user's `default` prompt for the
same video at background priority, through the same per-provider limiter as other background work (interactive requests go
first, `reserved_interactive` slots stay free). At most `[summary] auto_long_max_concurrent` (2) such jobs run at once, counting
the transcript fetch; a panel request that finds them all busy skips queuing, and the next panel request for that video tries
again. Nothing is queued when the long prompt is already cached, running or recently failed, when it is the same prompt as the
panel one, or for requests that name a prompt explicitly. When you then open the Summary view the long summary is usually
ready. If it is not, your request starts its own interactive run (the background one is cancelled), and a failed background job
never makes your request fail. Long summaries cost model time for every video you focus, so this is off unless you want it.

## Hosting at a short URL

Any URL that returns the JSON works: a gist, a static site, a file on your backend's reverse proxy, a URL shortener (redirects are
followed, up to 5). Imports must be `http(s)` on the default port and resolve to public addresses (private and loopback targets
are refused to protect the server); `summary.import_allow_hosts` exempts exact host names, for example a file server on your
LAN. The size cap is `summary.max_import_bytes` (256 KiB).

## Import, refresh, edit

- **TV**: *Settings, u·tubot, Prompts, Import from URL*, *Refresh all*, and the *Default prompt* choice. A setup can list
  `prompt_set_urls` ([server.md](server.md)); the app imports them right after pairing.
- **Web UI** (`/`, signed in): *Prompts* imports by URL, refreshes, edits JSON in place (*Validate* shows the problems, *Save set*), starts *New from template*, deletes, picks the two defaults and tries a prompt on a video.
- **API**: `POST /v1/prompts/import {"url": "..."}` (replaces the set with the same id and remembers `source_url`),
  `POST /v1/prompts/refresh` (re-fetches every set that has a source URL), `PUT /v1/prompts/sets/{id}` (upload),
  `PUT /v1/prompts/default {"key": "set/prompt"}`, `PUT /v1/prompts/panel-default {"key": "set/prompt"}`.

## Iterating without rebuilding anything

1. In the web UI tap *Edit JSON* on a set, change a prompt, *Validate*, *Save set*.
2. Under *Try a prompt* paste a video link or id, pick the prompt (or choose *Ad-hoc text* and type one, which is not cached
   long), press *Run*. A video without captions offers *Transcribe in background*.
3. Repeat. Summaries are cached by (video, prompt key, hash of prompt content, language), so editing a prompt invalidates only that
   prompt's results and unchanged prompts stay instant.

## Example 1: a general set

```json
{
  "tubeai_prompt_set": 1,
  "id": "everyday",
  "name": "Everyday",
  "version": "1",
  "prompts": [
    {
      "id": "tldr", "label": "TL;DR", "default": true,
      "system": "You summarize YouTube videos for a viewer using a TV remote. Be faithful to the transcript and never invent details. Plain text, no preamble. Reply in {language}.",
      "template": "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\nTranscript:\n{transcript}\n\nGive a TL;DR as 5 short bullet points starting with '- '. Lead with the single most important takeaway. At most 900 characters.",
      "max_tokens": 500
    },
    {
      "id": "worth-it", "label": "Worth watching?",
      "system": "You give a blunt, spoiler-free verdict on whether a video is worth the time. Reply in {language}.",
      "template": "Title: {title}\nDuration: {duration}\n\nTranscript:\n{transcript}\n\nIn 3 sentences: what it covers, who it suits, and whether skipping to a part is enough.",
      "max_tokens": 250
    }
  ]
}
```

## Example 2: learning and a stronger model for one prompt

```json
{
  "tubeai_prompt_set": 1,
  "id": "study",
  "name": "Study notes",
  "version": "1",
  "prompts": [
    {
      "id": "outline", "label": "Outline with timestamps", "default": true,
      "system": "You turn video transcripts into study outlines. Use only the transcript. Reply in {language}.",
      "template": "Title: {title}\n\nTranscript (with [mm:ss] markers):\n{transcript}\n\nWrite a nested outline of the main sections. Start each top-level line with the [mm:ss] where it begins.",
      "max_tokens": 900
    },
    {
      "id": "quiz", "label": "5 quiz questions",
      "system": "You write short quiz questions with answers from a transcript. Reply in {language}.",
      "template": "Title: {title}\n\nTranscript:\n{transcript}\n\nWrite 5 questions that test understanding, each followed by a one-line answer.",
      "max_tokens": 700,
      "model": "openrouter:anthropic/claude-sonnet-5.5"
    },
    {
      "id": "answer", "label": "Answer the question",
      "system": "You answer the question a video title poses, using only the transcript. Reply in {language}.",
      "template": "Title: {title}\nQuestion: {question}\n\nTranscript:\n{transcript}\n\nAnswer in at most 3 sentences. If the video does not answer it, say so.",
      "max_tokens": 250
    }
  ]
}
```

The `model` of the quiz prompt refers to a provider named `openrouter` in the server config; the other prompts use the summary model.

## Example 3: your own panel prompt

A short prompt that runs on the fast glance model. Import the set, then choose it as the side panel prompt under *Prompts, Defaults* in the web UI or
`PUT /v1/prompts/panel-default {"key": "quick/one-line"}`.

```json
{
  "tubeai_prompt_set": 1,
  "id": "quick",
  "name": "Quick",
  "version": "1",
  "prompts": [
    {
      "id": "one-line", "label": "One line",
      "system": "You write one-line video summaries for a TV panel. Plain text, no preamble. Reply in {language}.",
      "template": "Title: {title}\nQuestion the title poses, if any: {question}\n\nTranscript:\n{transcript}\n\nIf the title poses a question or teases a reveal, answer it first in one specific sentence. Otherwise give the gist in one sentence. At most 160 characters.",
      "max_tokens": 100,
      "task": "glance"
    }
  ]
}
```
