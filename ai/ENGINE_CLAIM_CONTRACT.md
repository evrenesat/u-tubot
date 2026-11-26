# u·tubot engine claim contract v1

The backend claims the big local engine through a small HTTP service; it does not know what stands behind the service.
This file freezes the wire contract between that backend and that service (checkpoint P0 of
[`ai/CUT_MODES_PLAN.md`](CUT_MODES_PLAN.md), Phase 2). The service side, the gateway and the mode switch are specified in
the companion plan; both plans link to this file. The contract is additive: a change needs a new owner decision and an
update to both plans, never an edit that silently changes a field or a reason.

No address, token or other deployment detail belongs in this file. `<url>` is whatever `[engine_claim] url` holds in the
backend's own config; the token comes from `token_env` only.

## Transport and authentication

- JSON, UTF-8. Requests that carry a body send `Content-Type: application/json`.
- `<url>` has no trailing slash. `POST <url>` asks for a claim; the other paths hang below it.
- Every request carries `Authorization: Bearer <token>`, the value of the environment variable named by
  `[engine_claim] token_env`. The token is scoped to claims on one engine.
- Missing or unknown token: `401 {"error":"unauthorized"}`. A token that is not scoped to the requested engine:
  `403 {"reason":"forbidden"}`.
- Times are RFC 3339 strings in UTC (`2026-11-24T20:00:00Z`). Durations are integer seconds. Ids are opaque strings.
- The backend never logs the address or the token, and the job report carries neither.

## Backend configuration

| Key | Default | Meaning |
|---|---|---|
| `url` | (required) | Base URL of the claim service; without it the `claimed` route is unavailable |
| `token_env` | (required) | Name of the environment variable holding the bearer token |
| `engine` | (required) | Engine name sent with a claim; the token must be scoped to it |
| `ttl_s` | `1800` | Requested lifetime of a claim; the service may grant less |
| `renew_every_s` | `300` | Interval of the backend's renewal timer |
| `renew_retry_s` | `20` | Retry interval when a renewal fails in transport |
| `claim_wait_max_s` | `900` | This backend's outer wait guard, measured against the first `ready_by` |
| `release_idle_s` | `60` | Idle time after which a claim with no prime job is released |
| `claim_retry_max` | `1` | How many times a lost claim is asked for again in the same build |

The route `claimed` is unavailable while `[engine_claim]` is absent. Only prime-class jobs reach this code; there is no
claim call on any path a normal user's request takes.

## Claim object

Every answer that returns a claim (the `POST` grant, `GET` by id, and the lookup by `client_ref`) uses this object:

```json
{
  "id": "<opaque>",
  "state": "draining|active|released|expired|failed",
  "expires_at": "2026-11-24T20:00:00Z",
  "max_expires_at": "2026-11-24T22:00:00Z",
  "ready_by": "2026-11-24T20:00:00Z",
  "waiting_for": "runs|idle|model",
  "link": "<the service's own page, optional>",
  "reason": "<on failed only>"
}
```

- `state`: `draining` (not yet usable), `active` (usable now), or a terminal state `released`, `expired`, `failed`.
- `expires_at`: the moment the service will expire the claim if it is not renewed. This is the only expiry the backend
  uses; it never computes one from its own clock and `ttl_s`.
- `max_expires_at`: the latest moment the claim may ever be renewed to.
- `ready_by`: the moment by which the service will have made the claim `active` or failed it. It is present on every
  grant and is used for the "waiting for the engine, N min left" line.
- `waiting_for`: present while `draining`; see the D-P11 section.
- `link`: optional; the service's own page for the claim. The backend may show it but never parses it.
- `reason`: present when `state` is `failed`; one of the reasons below.

## Time and waiting rules

- Only the service's `expires_at` and `max_expires_at` count. A backend whose clock runs slow still treats a claim that
  the service calls expired as lost.
- `ttl_s` is a request, not a promise. The service may grant a shorter life and caps it at its own limits;
  `expires_at` and `max_expires_at` are authoritative.
- The service owns the wait: it waits for what has to finish and fails the claim itself at `ready_by` if it cannot make
  it `active`. A `draining` claim that is given up ends as `failed` with one of the reasons below.
- `claim_wait_max_s` is only this backend's outer guard. The backend compares it with the first `ready_by`; if
  `ready_by` lies further away, a smaller `claim_wait_max_s` is a logged configuration error and `ready_by` is used.
  The guard never shortens the service's own wait and never sends the request to the cloud.
- A `409` on asking ends the wait at once. A `201` that is already `active` needs no wait.
- The remaining minutes shown in the request and the job report come from `ready_by`, not from `expires_at`.

## Endpoints

### `POST <url>` — ask for a claim

Request:

```json
{
  "engine": "<name>",
  "reason": "<this backend's job id>",
  "ttl_s": 1800,
  "client_ref": "<opaque backend instance id>"
}
```

- `reason` is the backend's job id. It says nothing about the user or the video.
- `client_ref` is an opaque, non-empty string of at most 128 characters that the backend chooses (its instance id). It is
  stable across restarts. The service stores it without interpreting it; the backend finds its own claim again through
  it.
- The holder is whoever the bearer token belongs to. At most one claim per engine and `client_ref` is open at a time; a
  backend looks up its open claim before asking.
- Answers: `201` with the claim object; `409 {"reason": "...", "holder_kind": "..."}` with one of the reasons below
  (`holder_kind` accompanies `held`); `401` or `403` as above.

### `POST <url>/<id>/renew` — keep it alive

- No body required. A renewal may extend `expires_at` but never beyond `max_expires_at`.
- Answers: `200 {"expires_at": "2026-11-24T20:00:00Z"}` with the new expiry; or `409 {"reason": "max_reached"}` when
  `max_expires_at` is reached, or `409 {"reason": "gone"}` when the claim is no longer open.
- The backend renews on its own timer every `renew_every_s`, independent of the describing loop, so a slow grid cannot
  stall it. A failure in transport is retried every `renew_retry_s` until 60 s before `expires_at`; a `409` or reaching
  that point means the claim is lost.

### `DELETE <url>/<id>` — give it back

- Answers `200` when the claim is released, and also when it was already closed; `404 {"reason": "not_found"}` for an id
  the service never issued.
- The backend sends a `DELETE` on every way of giving up: a failed claim, its guard running out, a dismissed request, a
  cancelled job, an idle release and shutdown, so the engine is never held for nobody. A killed backend releases nothing;
  the service's expiry ends the claim.

### `GET <url>?engine=<name>&client_ref=<ref>` — look up my open claim

- Answers `200` with the claim object when the caller has an open (`draining` or `active`) claim for that engine and
  `client_ref`; otherwise `404 {"reason": "not_found"}`. A claim of another token is never returned; it reads as `404`.
- On start the backend looks up its claim this way and continues it if a prime job is waiting, else releases it.

### `GET <url>/<id>` — read a claim

- Answers `200` with the claim object, including `released`, `expired` and `failed`; `404 {"reason": "not_found"}` when
  the id is unknown or belongs to another token.

## `409` and failed-claim reasons

Every reason below can be a `409` on asking and can end a `draining` claim as `state: "failed"`. The sentence is what the
request shows next to the Quick offer; none of them reads like a fault of the video or of the user.

| Reason | Meaning | Sentence |
|---|---|---|
| `held` | The engine is already claimed. `holder_kind` is `owner` for the owner's own claim, `other` for any other holder (including this backend's own open claim) | `owner`: "The engine is in use by the owner right now." `other`: "The engine is in use right now." |
| `other_mode` | The engine is in another mode, such as video mode; only the owner leaves it by hand | "The engine is in video mode right now." |
| `engine_down` | The engine is unreachable or off | "The engine is not reachable right now." |
| `actuator_failed` | The mode switch or model change failed | "The engine could not be prepared right now." |
| `runs_busy` | Agent runs already on the engine could not be moved to the cloud replacement, or work in flight did not end | "Other work on the engine did not finish in time." |
| `drain_timeout` | The engine did not become idle and ready before `ready_by` | "The engine did not become free in time." |
| `max_reached` | The claim reached its maximum lifetime and cannot be renewed | "This claim reached its time limit." |
| `cooldown` | The claimer is in the pause that follows a claim | "The engine was claimed a short while ago; try again in a few minutes." |
| `budget` | The claimer has used its daily claim budget | "The engine has used its claim time for today." |

A reason that ends a request also sets the request's `fallback` to Quick (phase 1, section 2.8). The grids already
described stay cached, so a later request continues from them.

## D-P11: runs already on the engine

The owner decided (24 Nov 2026) that a claim takes the engine at once:

- Agent runs already on the engine are switched to the cloud replacement in mid-conversation and marked as switched in
  their run record. New agent work goes to the replacement for its whole run. Nothing is frozen or stopped.
- The claim does not wait for those runs to finish. `waiting_for: "runs"` means the service is moving them to the
  replacement, not waiting for their completion.
- The only waits are `waiting_for: "idle"` for the model requests already in flight to end (the idle check) and
  `waiting_for: "model"` for the model change. `runs_busy` means moving the runs or ending the in-flight work failed;
  `drain_timeout` means the idle check or the model change did not finish before `ready_by`.

## Lifecycle from the backend

- Ask when a prime job first needs the `claimed` route (before its first grid) and poll the claim while it is
  `draining`.
- Under any claim `describe_concurrency` is 1 until a memory budget for parallel requests has been measured.
- A lost claim, or any failure on the `claimed` route (a refusal, a not-found, an engine or memory-guard error, a claim
  that ended while the request was running), ends the current grid's request as failed and stops the job at that grid.
  The backend releases what it holds, then asks once more (`claim_retry_max`) with the same wait limit. A second loss or
  failure in the same build ends it with the Quick offer; a memory-guard refusal is such a failure and is never retried
  in a loop.
- Release when no prime job needs the route any more, after `release_idle_s` (two cuts in a row share one claim), and on
  shutdown. A killed backend releases nothing; the service's expiry ends the claim.
- The job report gains the stage `claim` (asked, waited, state, reason, lost). No address or token of the service is
  logged; the token comes from `token_env` only.
