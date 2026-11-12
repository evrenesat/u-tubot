# LLM providers

The backend talks to chat-completions endpoints (`POST {base_url}/chat/completions`) in the OpenAI format. Anything that speaks it
works: a local server, a cloud API or an LLM router. You can configure several providers and pick one per task or per prompt.

```toml
[llm]
default_provider = "local"

[llm.providers.local]                  # first provider: a server on this machine
base_url = "http://127.0.0.1:11434/v1"

[llm.providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "UTUBOT_OPENROUTER_API_KEY"   # name of an environment variable, never the key itself

[llm.triage]
model = "llama3.2:3b"
```

Keys come from the environment (for systemd, `/etc/utubot/env`). A provider without `api_key_env` is called without
authentication.

## Examples

| Provider | `base_url` | Notes |
|---|---|---|
| Ollama | `http://127.0.0.1:11434/v1` | `ollama pull llama3.2:3b llama3.1:8b`; model names are Ollama tags |
| llama.cpp server | `http://127.0.0.1:8080/v1` | `llama-server -m model.gguf`; one model per server, the name is mostly ignored |
| vLLM | `http://127.0.0.1:8000/v1` | model name as served (`--served-model-name`) |
| LM Studio | `http://127.0.0.1:1234/v1` | enable the local server |
| OpenAI | `https://api.openai.com/v1` | `api_key_env` required |
| OpenRouter | `https://openrouter.ai/api/v1` | `api_key_env` required; names like `anthropic/claude-sonnet-5.5` |
| LLM router / gateway | its OpenAI-compatible URL | your own aliases (`fast`, `worker`) as model names |

The built-in default `base_url` is `http://127.0.0.1:8000/v1` and the built-in model names (`fast`, `worker`) are
placeholders: set the models for your provider.

## Tasks and models

| Table | Used for | Output |
|---|---|---|
| `[llm.triage]` | batched title classification for every card (clickbait, low quality, topics, title question) | JSON, many titles per call; runs constantly, so make it small and fast |
| `[llm.summary]` | prompt-set summaries and the summary panel | prose |
| `[llm.answer]` | `ask` and the answer to a title's question | prose |
| `[llm.analysis]` | insight and the transcript-based second tier (short answer, inflation) | JSON |
| `[llm.captions]` | optional caption translation | JSON array |

Each takes `model`, optional `provider`, `fallback`, `reasoning_effort`, `max_tokens`, `temperature`. A model may be written
`provider:model` (`model = "openrouter:anthropic/claude-sonnet-5.5"`). A prompt in a prompt set can set its own `model` the same way;
see [prompt-sets.md](prompt-sets.md).

Rules of thumb: triage reads only titles and short descriptions, so a 3B to 8B model is enough. Summaries read transcripts of
up to `summary.token_budget` tokens (24 000 by default; longer transcripts are map-reduced in `chunk_tokens` pieces or truncated),
so give the summary task a model with that much context and decent instruction following.

## Reasoning / thinking models

- `<think>...</think>` blocks in the answer are stripped, and JSON is extracted from prose or code fences. If a model returns bad
  JSON once, the backend asks again (`retries_on_bad_json`).
- `reasoning_effort` is sent to the endpoint only when you set it. For triage use `"none"` (or the lowest your provider
  accepts) so a reasoning model does not spend seconds per card. Endpoints that reject the field: leave it unset.
- `max_tokens` is the budget for the visible answer. The backend adds `[llm] reasoning_headroom_tokens` (default 2048) to
  every request so reasoning models can think without cutting the answer; a task may override it with its own
  `reasoning_headroom_tokens` (`0` for endpoints without reasoning). A prompt's `max_tokens` is an answer budget too.
- When the endpoint reports `finish_reason: length` the call is retried once with the answer budget doubled. If the text is
  still cut, it is returned with a trailing " …", logged as `kind=truncated`, and not cached long-term (summaries use the ad-hoc
  TTL), so a later request tries again.
- Prefer a non-reasoning or low-effort model for triage and the app's interactive summary panel; the TV waits for results.

## Cost and speed notes

- Triage is the volume: one call per `assess.batch_size` (25) titles, cached per video for `triage_cache_ttl_s` (7 days) and shared
  between users. Rows of already seen videos cost nothing.
- Transcript-based work (second tier, summaries) is capped: `assess.tier2_daily_cap_per_user` deep analyses per user per UTC day,
  and summaries only run for videos someone opens or focuses. Summaries are cached per (video, prompt content, language).
- Set `max_concurrent` on each provider to what its endpoint can take (default 2); see the next section.
- To watch spending on a paid API, put a cheap model on triage, a better one on summaries, and check the provider's dashboard
  after a day of normal use before raising the caps.
- A local model costs no money but latency matters: the app waits at most `assess.wait_ms_cap` (3 s) for triage and shows cards
  unmarked when the answer is late; results appear on the next load.

## Fail-fast endpoints and backpressure

Some endpoints and routers do not queue: when an engine is at its concurrency cap they answer at once with HTTP 503 (or 429),
sometimes with a `Retry-After` header. The TV asks for a verdict for every row it loads, so background triage can saturate such an
engine and an interactive request (summary, answer, insight) would fail. The backend handles this in four ways.

- **Per-provider limiter.** `[llm.providers.NAME] max_concurrent` (default 2) caps in-flight requests to that provider. Waiting
  requests are served by priority: interactive work (summary, ask, insight requested by a user) always goes before background
  work (triage, second-tier analysis, caption translation). `reserved_interactive` (default 1, never more than
  `max_concurrent - 1`) keeps that many slots unavailable to background work, so an interactive request finds a free slot
  instead of waiting for a long background call to end.
- **Retries.** 429, 502, 503, 504 and connection errors are retried with exponential backoff and jitter
  (`retry_base_s`, `retry_max_s`, `retry_max_attempts` in `[llm]`), honouring `Retry-After` (seconds or HTTP date). Slots are
  released while waiting. A call gives up at its deadline (`deadline_interactive_s` 45, `deadline_background_s` 120; the
  interactive one should not exceed `summary.wait_ms_cap` by much, because the client stops waiting then and the work continues
  in the background). Other 4xx responses are never retried.
- **Fallback models.** `fallback = ["provider:model", ...]` on any task table is tried in order when the primary is still busy
  or unavailable (busy after retries, connection errors, 5xx) but never after a 4xx. A prompt's own `model` is tried first and
  the task's `fallback` list follows it. The call deadline is split between the models in the chain.
- **Load shaping.** `/v1/assess` calls arriving within `assess.coalesce_ms` (300) of each other are merged: uncached videos are
  collected per topic list and sent as batches of up to `assess.batch_size`, so ten rows loaded in quick succession make one or
  two triage calls. A full batch is sent immediately. Videos already being triaged are not queued twice.

When every model in the chain stays busy, the `error` field of a summary, answer or insight reads "the language model is busy,
try again in a moment" instead of the generic failure message; no internal detail is exposed.

### Reasoning models and JSON

For triage and analysis the backend asks for `response_format: {"type": "json_object"}` when the provider sets `json_mode = true`
(default false; leave it off for endpoints that reject the field). If the model returns no usable JSON (empty `content` with only
`reasoning_content`/`reasoning`, output cut at `max_tokens`, or prose without JSON), the reasoning text is never parsed as the
answer: the call is retried once (`retries_on_bad_json`) with `max_tokens` raised to `json_retry_max_tokens` (6000) and a short
"Reply with JSON only" reminder. The failure kind (`empty`, `truncated`, `no-json`) is logged, never the content.
