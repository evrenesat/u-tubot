# Prompt sets

Summaries are produced by prompts you choose. A **prompt set** is a JSON file with several prompts. It can be hosted anywhere and
imported by URL, uploaded in the web UI or imported from the TV. Prompts are per user; a built-in set (`builtin`) always exists
(TL;DR, Answer the title, Key takeaways and more) and cannot be changed.

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
- `model`: optional, overrides the summary model: a model name or `provider:model` naming a provider from your config.

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
| `{question}` | the question a title poses, for "answer" style prompts |

Validate a file before hosting it: `uv run utubot prompts validate my-prompts.json`.

## Hosting at a short URL

Any URL that returns the JSON works: a gist, a static site, a file on your backend's reverse proxy, a URL shortener (redirects are
followed, up to 5). Imports must be `http(s)` on the default port and resolve to public addresses (private and loopback targets
are refused to protect the server); `summary.import_allow_hosts` exempts exact host names, for example a file server on your
LAN. The size cap is `summary.max_import_bytes` (256 KiB).

## Import, refresh, edit

- **TV**: *Settings, u·tubot, Prompts, Import from URL*, *Refresh all*, and the *Default prompt* choice. A setup can list
  `prompt_set_urls` ([server.md](server.md)); the app imports them right after pairing.
- **Web UI** (`/`, with your token): import by URL, edit JSON in place (*Save set*), start *New from template*, delete.
- **API**: `POST /v1/prompts/import {"url": "..."}` (replaces the set with the same id and remembers `source_url`),
  `POST /v1/prompts/refresh` (re-fetches every set that has a source URL), `PUT /v1/prompts/sets/{id}` (upload),
  `PUT /v1/prompts/default {"key": "set/prompt"}`.

## Iterating without rebuilding anything

1. In the web UI load a set into the editor, change a prompt, *Save set*.
2. Under *Try a summary* enter a video id, pick the prompt (or type ad-hoc prompt text, which overrides the selected one and is
   not cached long), press *Summarize*.
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
