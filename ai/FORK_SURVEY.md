# Fork survey and base decision (2026-11-12)

Scope: all 2,584 forks of yuliskov/SmartTube via the GitHub API; 1,235 pushed in
2026 were compared against upstream `master` (ahead/behind + unique commit
subjects), 443 have their own commits. Non-fork repos with SmartTube + AI in the
name were searched too. None is a "best in class AI" fork; the AI work that
exists is narrow and young (0 stars each).

| Fork | Stars | Ahead/behind | AI / relevant work | Verdict |
|---|---|---|---|---|
| cygnusx-1-org/electriceel | 41 | 206 / 71 | No LLM. Best filtering stack: hide-or-mark modes per filter, async pre-resolution of each row (`HiddenVideoResolver`), coloured card marks, keyword/category/age/collab/streamed filters, AiSList channel blocklists ("AI slop"), per-account settings, settings sync, active maintainer, merges upstream tags (32.68, cherry-picks 32.70s) | **Base** |
| briqt/t-smarttube | 0 | 9 / 69 | AI bilingual captions: OpenAI-compatible providers, caption session/timeline/translation pipeline (~9k lines), designed for conflict-free upstream tracking | Reference for caption injection |
| farajfarook/SmartTube | 0 | 5 / 134 | On-demand AI summary in the video context menu (Gemini + OpenAI-compatible), on-device transcript fetch | Idea already covered by our side panel |
| Migmags/SmartTube-AI-Filter-fork | 0 | 12 / 31 | "AI filter" = title keyword heuristics, no model | Not useful |
| dingba809/SmartTube | 0 | 15 / – | LLM subtitle translation, batch prefetch | Reference only |
| Samhouston010/SmartTube | 0 | 14 / – | Routes Persian captions through own server | Confirms the backend pattern |
| CodeSculptor/SmarterTube | 104 | 322 / – | Phone/tablet companion, no AI | Out of scope (TV) |

## Why Electric Eel

Four of the five wanted features are "decide per card, then hide or mark". Electric
Eel already holds each row until async lookups finish, then hides or marks with
a coloured label, so an AI verdict becomes one more lookup in that zip. With
upstream SmartTube we would have to build that machinery first. It is MIT and
the maintainer merges upstream releases.

Risk: it trails upstream (71 commits now) and is one maintainer. Mitigation: the
AI layer lives in its own packages with small hooks (`ai/APP_INTEGRATION.md`
lists them), so it can be moved onto upstream SmartTube if Electric Eel stalls.

## Architecture choice

Thin TV client + backend (`ai-backend/`). The TV only sends card metadata and
renders verdicts, panels and subtitle tracks; the backend owns yt-dlp, ASR,
diarization, prompt sets, per-user policy, caching and every model call
(any OpenAI-compatible endpoint: a local server, a cloud API or an LLM router). One APK serves several people
with different tokens and policies, and prompt iteration needs no APK rebuild.

## Repo layout

- `github.com/evrenesat/u-tubot`. Remotes: `electriceel` (base), `smarttube` (upstream).
- Electric Eel builds against sibling checkouts of `SharedModules` and `MediaServiceCore`
  (pins at time of fork: SharedModules 18ba193b, MediaServiceCore 173b3c30, electriceel 79ceafae).
