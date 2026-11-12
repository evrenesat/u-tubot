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

Each takes `model`, optional `provider`, `reasoning_effort`, `max_tokens`, `temperature`. A model may be written
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
- `max_tokens` usually includes reasoning tokens. For a reasoning model raise it (triage 2500 is the default; give summaries
  2000 or more), otherwise the answer is cut off.
- Prefer a non-reasoning or low-effort model for triage and the app's interactive summary panel; the TV waits for results.

## Cost and speed notes

- Triage is the volume: one call per `assess.batch_size` (25) titles, cached per video for `triage_cache_ttl_s` (7 days) and shared
  between users. Rows of already seen videos cost nothing.
- Transcript-based work (second tier, summaries) is capped: `assess.tier2_daily_cap_per_user` deep analyses per user per UTC day,
  and summaries only run for videos someone opens or focuses. Summaries are cached per (video, prompt content, language).
- Set `llm.max_concurrency` to what your endpoint can take (default 4). With a local model on a modest GPU use 1 or 2.
- To watch spending on a paid API, put a cheap model on triage, a better one on summaries, and check the provider's dashboard
  after a day of normal use before raising the caps.
- A local model costs no money but latency matters: the app waits at most `assess.wait_ms_cap` (3 s) for triage and shows cards
  unmarked when the answer is late; results appear on the next load.
