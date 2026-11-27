# Web settings: change every setting from the web app, the TV follows (plan, draft)

Status: draft 1, 27 November 2026. Nothing is implemented. This file is the plan only.
Owner request (27 November 2026): "Once I paired with the web app, I should be able to configure all settings from the
web app. Start with AI-related features, but even per-TV settings should be synced with the web. Full TV settings can
wait a little."
Related: #276 (accounts and services on the Account page), #248 and pull request #251 (Real-Debrid entry on the TV),
#232 (per-user AI provider keys and budgets), #202 (TV settings sections), #234 (voice consent per device), #200
(development mode, update interval), `ai/CONTRACT.md` ("Per-user settings"), `ai/BROWSER_EXTENSION_PLAN.md` (parity
rule, companion step C3), `ai/VOICE_CONTROL_PLAN.md` (the live server).

---

# Part 1: owner plan

## What changes for you

- The web app gets a **Settings** page. It shows all settings in groups. You can search it.
- The first group is **AI features**. It has the same switches as "AI features" on the TV.
- You change a value on the page. The page shows the old value and the new value. You press **Save**.
- Your TV gets the change in about 30 seconds while the app is open. A later step makes this about 3 seconds.
- Each setting shows which TV has the new value: "Applied on Living room, 12 s ago" or "Waiting for Bedroom TV".
- Each TV has its own tab. A TV can have a different value from your default. The tab shows these differences.
- You can still change settings on the TV. The web page then shows the TV's change.
- The TV keeps a copy of all settings. It works as before when the server is down.
- A **History** tab shows who changed a setting, where (web or which TV), and when.
- Real-Debrid and the stream add-on address (#276) are in the same system. The page shows only "set" and the last
  4 characters. The server keeps them encrypted.
- Nothing is lost at the start. On its first sync, a TV sends its current values to the server.

## Order of the work

1. **First usable step:** the AI feature settings, synced for one TV, with the Settings page and the History tab.
2. **Then:** settings that belong to one TV (updates, development mode, keys for cuts, text speed, voice).
3. **Then:** Real-Debrid, the add-on address and other accounts (#276).
4. **Later:** all other TV settings (player, look, remote control). This step gets its own plan.

## Decisions needed from you

| # | Question | Recommended |
|---|---|---|
| D1 | Web and TV change the same setting. Which one wins? | The change that reaches the server last wins. One exception: a change made on a TV while it was offline does not replace a newer web change. TV clocks are often wrong, so we do not use them. |
| D2 | May a TV send its Real-Debrid token to the server? | Only after it asks you one time on that TV. No silent upload. |
| D3 | A TV has its own value. You change your default on the web. What happens? | The TV keeps its own value. The page shows "1 TV has its own value" with a button "Use my default". |
| D4 | What are the IMDb details for (#276)? | No recommendation. We build Real-Debrid and the add-on address first. This does not block the plan. |

## How you try the first step

Open the web app, go to Settings, switch "Summary panel" on, save. Look at the TV: the panel is on in about
30 seconds and the page shows "Applied". Change "Mark only" on the TV: the page shows it after a refresh.

---

# Part 2: agent plan

## 1. Facts checked (27 November 2026, `main` at 7e11d20d)

| Fact | Where |
|---|---|
| A per-user settings document exists: `GET/PUT /v1/me/settings` with `settings`, `overrides`, `defaults`, `choices`, a `version` that rises on every change, compare-and-set writes (409, 428) | `ai-backend/src/utubot/settings.py`, `ai/CONTRACT.md` "Per-user settings" |
| Its values live in `policy_overrides(user, json, version, updated_at)` and the two prompt-default tables: "one store, no copies" | `settings.py`, `db.py` |
| `GET /v1/me` already carries `settings_version` | `ai/CONTRACT.md` |
| The TV never reads the document. It calls `/v1/me` only for `user` and `features` | `UtubotParser.parseMe`, `UtubotClient`; also stated in `ai/BROWSER_EXTENSION_PLAN.md` section 1 |
| The web UI already has a "TV settings" card that writes `settings.tv.*` with the note "applied to your TVs once they read settings from it (a later app release)". These values have no effect today | `web/ui/js/pages/devices.js` `tvSettingsForm` |
| Server and TV disagree on one setting: server `tv.summary_delay_ms` is 0 to 10000, default 700; TV `panel_delay_ms` is one of 1000, 1800, 3000, 5000, default 1800 | `config.py` `UserPolicy`, `UtubotSettings` |
| `mark_only` exists twice: server `filtering.mark_only` and the TV switch | `UserPolicy`, `UtubotSettings` |
| Server `tv.update_checks` has no TV counterpart; the TV has `update_interval_minutes` and `development_mode` instead | `UserPolicy`, `UtubotSettings` |
| All u·tubot TV values are in one `SharedPreferences` file, `utubot_settings`, behind getters and setters of `UtubotSettings` | `UtubotSettings.java` |
| Paired devices are rows of `device_tokens(id, user, device, created_at, last_used)`; voice consent is `device_voice` per device | `db.py`, `voice.py` |
| A user's own AI provider key is stored in clear text: `user_providers.api_key` | `db.py`, `userproviders.py` |
| The backend has no encryption library and no master key setting; other shared secrets come from environment variables named in `[security]` | `pyproject.toml`, `config.py` `SecurityConfig` |
| The TV has no standing poll of the backend except the update check and the followers of running jobs; long polls with `wait_ms` are an existing pattern | `UtubotUpdateSchedule`, `UtubotCutWatcher` |
| The TV is not yet a client of the live server (voice checkpoint 3 is not started) | `ai/VOICE_CONTROL_PLAN.md` status |
| The Real-Debrid token and the add-on address are typed on the TV and kept in the same preferences; pull request #251 (draft, conflicts with `main`) adds a user-facing entry on the device | `UtubotSettings`, #251 |
| Web UI screenshots are taken by `docs/screenshots/webui/capture.cjs`, which fails on console errors and on sideways scrolling at 360 px | `docs/development.md` |
| The emulator mock backend has `/v1/me` and voice routes, no settings route | `scripts/emulator_mock_backend.py` |

## 2. Inventory of the TV's settings today

Scope: **user** = one value per person; **user+tv** = a user value that one TV may override; **tv** = belongs to one
device. Remote: **rw** = safe to change from the web; **ro** = shown on the web, changed only on the TV; **no** = never
leaves the TV. Phase: the step of section 9 that syncs it.

### 2.1 AI features (first)

| TV entry (`UtubotSettings` key) | Type, default, range | Server today | Scope | Remote | Phase |
|---|---|---|---|---|---|
| Assess videos (`assess`) | bool, true | setup default only | user+tv | rw, confirm when switched off | MVP |
| Mark only, never hide (`mark_only`) | bool, false | `filtering.mark_only` | user+tv | rw | MVP |
| AI answer in the video menu (`answer_in_menu`) | bool, true | setup default only | user+tv | rw | MVP |
| Summary panel (`summary_panel`) | bool, false | `tv.summary_panel` | user+tv | rw | MVP |
| Summary delay (`panel_delay_ms`) | int ms, 1800, 0 to 10000 | `tv.summary_delay_ms` (700) | user+tv | rw | MVP |
| Auto captions (`auto_captions`) | bool, true | `tv.auto_captions` | user+tv | rw | MVP |
| Apply ready cuts (`auto_cuts`) | bool, false | none | user+tv | rw | MVP |
| Assess wait (`wait_ms`, no TV entry) | int ms, 1200, 0 to 3000 | none | user+tv | rw, "advanced" | MVP |
| Default prompt, panel prompt | prompt key | `prompts.default`, `prompts.panel_default` | user | rw (exists) | MVP (shown) |
| Models per feature (glance, summary, answer, triage, analysis) | model value | `models.*`; admin override per feature in `feature_models` | user (admin: server) | rw (exists) | MVP (shown) |
| Filters: topics and thresholds, answer in label | lists, 0 to 1.01 | `filtering.*` | user | rw (exists) | MVP (shown) |
| Summary language, long summaries | text, bool | `summaries.*` | user | rw (exists) | MVP (shown) |
| Automatic transcription, translate captions to | enum, int, text | `transcripts.*` | user | rw (exists) | MVP (shown) |
| Default cut mode | quick or watched | `cuts.cut_mode` | user | rw (exists) | MVP (shown) |
| Text scroll speed (`auto_scroll_speed`) | int px/s, 45, one of 30, 45, 60 | none | tv (depends on the screen) | rw | 2 |
| Keys that jump between cut parts (`cut_jump`) | enum left_right, up_down, off | none | tv (depends on the remote) | rw | 2 |
| Voice: on, listen mode, spoken replies | per device, consent needed | `device_voice` | tv | rw (exists; switching on shows the consent text) | 2 (linked) |
| Voice history retention | int days, 0 to 365 | `user_voice` | user | rw (exists) | 2 (linked) |
| Caption storage: usage, delete older than 30, 90, 365 days, delete all | action | none | tv | ro (usage reported); delete stays on the TV | 2 |
| Prompt sets: import, refresh | action | prompt routes | user | exists on the Prompts page | none |

### 2.2 Per-TV, not AI

| TV entry (key) | Type, default, range | Scope | Remote | Phase |
|---|---|---|---|---|
| Update check interval (`update_interval_minutes`) | int, 5, one of 5, 15, 60, 360 | tv | rw | 2 |
| Development mode (`development_mode`) | bool, true on the built-in flavor | tv | rw, confirm | 2 |
| Check for app updates (server `tv.update_checks`, no TV entry) | bool, true | user+tv | rw; the TV starts to obey it (off = no automatic check, the manual check stays) | 2 |
| Browse refresh interval (`browse_refresh_minutes`) | int, choices of `BrowseCachePolicy` | tv | rw | 2 |
| Films developer entry (`films_developer`), skip list (`films_skips`), IMDb test id (`films_imdb_id`) | developer tools | tv | no | none |

### 2.3 Secrets (#276)

| Entry (key) | Scope | Remote | Phase |
|---|---|---|---|
| Real-Debrid token (`films_rd_token`) | user, delivered to the user's TVs | write-only on the web; "set" and last 4 characters | 3 |
| Stream add-on address (`films_addon_url`; may hold a key) | user, delivered to the user's TVs | as above; the host is shown, the path is not | 3 |
| Own AI provider key (`user_providers`, server only) | user, never delivered | exists (`PUT /v1/me/provider`); moves to the encrypted store | 3 |
| IMDb / Trakt | open (D4) | not designed | after D4 |

### 2.4 Device-only: never synced

Backend address (`url`), device token (`token`), update address (`update_url`): changing them from the server could cut
the TV off from the server, and the token is the TV's identity. Local state, not settings: `pair_prompt_done`,
`setup_prompt_done`, `dismissed_update`, `dismissed_update_code`, `cut_legend_shown`, `pending_prompt_sets`, the What's
new marker, the cut waitlist. The web shows per TV, read-only: name, app version, schema version, last sync, caption
storage usage.

### 2.5 Everything else on the TV (later)

The player, interface, remote-control and account settings inherited from the base app live in other preference
classes. They are not listed here. Phase 4 starts with a generated inventory of those keys and gets its own plan
revision; until then they stay on the TV.

## 3. One schema

One file, `ai/settings/schema.json`, is the only place that names a setting. The backend loads it (packaged with the
wheel), serves it at `GET /v1/settings/schema` (ETag = `schema_version`), the web UI renders from it, the TV build puts
it in its assets, and the extension bundles it. A hand-written list of settings anywhere else is a defect.

```json
{"schema_version": 1,
 "groups": [{"id": "ai", "title": "AI features", "order": 10}],
 "settings": [
  {"key": "ai.summary_panel", "group": "ai", "title": "Summary panel",
   "description": "Show the side panel with a summary while you browse.",
   "type": "bool", "default": false, "scope": "user", "device_override": true,
   "remote": "rw", "confirm": false, "clients": ["tv", "extension"], "since": 1,
   "store": "policy:summary_panel", "tv_pref": "summary_panel"},
  {"key": "ai.panel_delay_ms", "type": "int", "default": 1800, "min": 0, "max": 10000, "step": 100,
   "presets": [1000, 1800, 3000, 5000], "unit": "ms", "store": "policy:summary_delay_ms", "tv_pref": "panel_delay_ms"}
 ]}
```

- `type`: `bool`, `int` (`min`, `max`, `step`, optional `presets`), `enum` (`choices` with labels), `string`
  (`max_len`), `list` (`max_items`, `max_len`), `model`, `prompt`, `secret` (`deliver`: `tv` or `none`).
- `scope`: `user` or `device`. `device_override: true` lets one TV hold its own value of a user setting.
- `remote`: `rw`, `ro`, `none`. `confirm: true` asks again before the save.
- `store`: where the value lives. `policy:<field>` is the existing `policy_overrides` field (no copy is made);
  `prompts:<key>`; `values` is the new table; `secrets`; `voice` (existing tables, linked).
- `tv_pref`: the TV preference key; `since`: the first schema version that has the key.
- Titles are at most 60 characters, descriptions at most 160; both are required (a test checks it).
- Versioning: `schema_version` is one integer. Adding a key raises it. A client sends its version and the server never
  sends a key with a higher `since`; a client ignores keys it does not know. A rename keeps the old key as `alias` for
  two schema versions. A key is never reused with another meaning. Changing a default is a schema change and is
  recorded in the History of every user it affects.
- Decided mismatches: `ai.panel_delay_ms` takes the TV's default (1800) and the server's range; the TV shows its four
  presets and "Custom (700 ms)" for another value. `ai.mark_only` is one key backed by `filtering.mark_only`; checkpoint
  1 records which side acts on it today and keeps that behaviour. `updates.checks` keeps `tv.update_checks`.

## 4. Sync model

### 4.1 Truth and resolution

The server is the source of truth for every key with `remote` `rw`. The value a TV uses is the first that exists of:
the TV's own override, the user's value, `[users.policy]`, `[default_policy]`, the server setting an unset field
follows (as today), the schema default. The TV keeps the resolved values in its existing preferences, and every
feature keeps reading `UtubotSettings` getters: the read path does not change and needs no network.

### 4.2 Storage (additive)

- `settings_values(user, device_id, key, json, rev, changed_at, PRIMARY KEY(user, device_id, key))`: device overrides
  (any key with `device_override` or scope `device`) and user values of keys with `store: values`. `device_id` is `''`
  for a user value.
- One counter per user: the existing `policy_overrides.version`. Every settings write of any kind (document `PUT`,
  device channel, secret, admin edit) raises it by one in the same transaction, and the changed key gets `rev` = the new
  version. `/v1/me` `settings_version` stays the one cheap "something changed" signal.
- `device_settings_state(device_id PRIMARY KEY, user, applied_version, applied_at, schema_version, app_version,
  last_sync_at, migrated_at, report_json)`.
- `settings_audit(id, user, device_id, key, old_json, new_json, by_user, via, actor_device_id, at, outcome)`; `via` is
  `web`, `tv`, `extension`, `admin`, `migration`, `server`; `outcome` is `applied` or `superseded`. For a `secret` key
  `old_json` and `new_json` are only `"set"` or `"cleared"`. Kept 180 days and at most 5,000 rows per user (pruned on
  write).

### 4.3 Device channel

- `GET /v1/device/settings?have=<version>&schema=<n>` (device token) ->
  `{"version": 41, "schema_version": 1, "settings": {"ai.summary_panel": {"v": true, "rev": 39, "from": "user"}},
  "secrets_rev": 3}` with every key this client and schema may see, resolved for this device (`from`: `device`, `user`
  or `default`). When `have` equals the version: `{"version": 41, "unchanged": true}`. A config token or a browser
  session gets `400` (no device behind it).
- `POST /v1/device/settings` `{"schema_version", "app_version", "applied_version": 41, "initial": false,
  "changes": [{"key", "value", "base_rev": 39}], "report": {"caption_store_bytes": 123}}` -> the same document as the
  `GET` plus `"results": [{"key", "outcome": "applied|superseded|invalid|not_remote"}]`. It records what the TV has
  applied and takes the TV's own changes. At most 200 changes and 64 KiB.
- `GET /v1/me/settings/status` (web) -> `{"version", "devices": [{"id", "device", "applied_version", "applied_at",
  "last_sync_at", "schema_version", "app_version", "syncs": true, "overrides": ["ai.summary_panel"],
  "pending": ["ai.auto_cuts"]}]}`; `pending` is every key whose `rev` is above the TV's `applied_version`.
- `PUT /v1/me/devices/{id}/settings` `{"version", "settings": {key: value|null}}`: a TV's overrides from the web
  (`null` removes one). `GET /v1/me/settings/history?limit=50&key=&device=` reads the audit. The document `PUT` stays
  and accepts the schema's dotted keys beside the old sections.
- `/v1/me` gains `features.settings_sync` (true when `[settings_sync] enabled`). All routes are additive; with the
  switch off they answer `404` after authentication and old clients see nothing new.

### 4.4 Conflict rule (D1)

Per key, by the server's order of arrival, never by a device clock. A web write is a compare-and-set on the document
version, as today. A TV write carries the `rev` of the key that the TV last saw (`base_rev`): equal to the key's
current `rev` -> applied; lower -> `superseded`, the server's value stays, the TV takes it and shows one message
("Summary panel was changed on the web while this TV was offline; the web value is used"), and the History keeps the
lost value. A TV change always lands as that TV's override, never as the user's default (D3); "Use for all my TVs" on
the web promotes it.

### 4.5 Offline behaviour

- A change on the TV applies at once and goes to an outbox in the preferences (one entry per key, the newest value, the
  `base_rev` of the first unsent change). The outbox survives a restart and is sent on the next sync.
- A sync never blocks the start or a screen: it runs off the main thread with a 5 s timeout and backs off from 30 s to
  10 minutes on errors. With the server down the TV behaves as before the sync; no setting falls back to a default.
- A server without the routes (`404`) switches the sync off until the backend version from `/v1/health` changes.
- An unpaired TV has no sync. A TV paired to another user starts from that user's values after a new first sync.

### 4.6 How fast

- MVP: the TV syncs at start, when the app returns to the front, when a settings screen opens, right after a local
  change, and every 30 s while the app is in front (one small request; "unchanged" answers are under 300 bytes).
- Checkpoint 5: `GET /v1/device/settings` takes `wait_ms` up to 20000 and answers the moment the user's version
  changes (the existing long-poll pattern).
- Later: when the TV is a screen of the live server, a `settings` frame `{"t":"settings","version"}` triggers the same
  pull. The HTTP path stays the fallback and the only path without the live server.

## 5. Web UI

- New page `#/settings`, in the wide navigation and under More on a phone. Tabs: **My settings**, one tab per TV (its
  name; a phone shows a picker), **History**. A search box filters by title, description and key as you type; groups
  with no match fold away. Every row has a stable link (`#/settings/ai.summary_panel`).
- A row: title, description, the control for its type, "Default: ..." with a reset, and the applied chips: "Applied on
  Living room, 12 s ago", "Waiting for Bedroom TV (last seen 14:02)", "Bedroom TV has its own value: 3 s" with "Use my
  default". A TV whose app is too old shows "This TV cannot sync yet (update the app)".
- Edit in place with confirm: a change is staged, not sent. A bar at the bottom reads "Review 2 changes"; it lists
  old -> new per setting, with **Save** and **Discard**. Keys with `confirm: true` ask once more in words ("Stop
  assessing videos on all your TVs?"). A `409` reloads and keeps the staged changes that still apply.
- The page asks `GET /v1/me/settings/status` every 5 s while it is visible, so chips move without a reload.
- A TV tab shows that TV's resolved values, marks overrides, edits them, has "Copy all settings from another TV" (a
  staged change like any other) and the read-only facts (app version, last sync, caption storage).
- History: time (the browser's zone), who, where ("web", the TV's name, "admin: name", "first sync"), setting,
  old -> new. Secrets read "changed" or "removed".
- Admins get the same page for another user from Admin (the existing `/v1/users/{name}/settings` pattern); the History
  names the admin. Per-feature server models stay on Admin and are linked from the Models group.
- The existing pages (Filters, Models, Captions, Prompts, the cut mode card) stay and link to their group; the "TV
  settings" card on TVs is replaced by a link to the TV's tab. Its help text is in the page: no link to GitHub.
- Before merge of every web checkpoint: screenshots at 1440 and 390 px on a database that has two TVs, one offline,
  one override and ten history rows; `capture.cjs` gains the 390 and 1440 widths and the new page.

## 6. Secrets (#276)

- Storage: `user_secrets(user, key, nonce, ciphertext, key_id, last4, updated_at, rev, PRIMARY KEY(user, key))`.
  AES-256-GCM (`cryptography`, added to `pyproject.toml` and `THIRD_PARTY.md`), a fresh 96-bit nonce per write, the
  user and key as associated data so a row cannot be moved to another user or field.
- Master key: 32 random bytes, base64, from the environment variable named by `[security] secrets_key_env` (default
  `UTUBOT_SECRETS_KEY`); never in `config.toml`, the database or git. Without it every secret route answers
  `503 {"error":"secret storage is not set up on this server"}`, the Account section says so, and nothing is stored in
  clear text. `utubot secrets rotate` re-encrypts with a new key (`key_id` names the key of a row);
  `utubot secrets check` decrypts every row and prints only counts.
- Web: Account page, "Accounts and services". `GET /v1/me/secrets` -> `[{"key", "set": true, "last4": "4f2a",
  "updated_at", "delivered_to": [{"id", "device", "at"}]}]`; `PUT /v1/me/secrets/{key}` `{"value"}`;
  `DELETE /v1/me/secrets/{key}`. No route returns a whole value to a browser. The add-on address is checked as a URL
  (https, or http for private hosts, the app's rule) and shows its host only.
- TV: `GET /v1/device/secrets?have=<secrets_rev>` (device token only, `no-store`) returns the caller's `deliver: tv`
  secrets. The TV asks only when `secrets_rev` of the settings answer changed. It keeps them in its private
  preferences, wrapped with an Android Keystore key where the device has one. A secret removed on the web is removed on
  the TV at the next sync. The server never calls Real-Debrid.
- Logging: values never reach a log line, an error text, the audit, a failure record or a test snapshot. The request
  body of the secret routes is excluded from any request logging.
- Upload from the TV (D2): a TV that holds a token the server does not have asks once: "Keep this Real-Debrid token on
  your server so your other TVs get it?" Yes sends it with `PUT /v1/me/secrets/{key}`; Not now is remembered.
- `user_providers.api_key` moves into the same store in the same checkpoint (a migration encrypts the rows and blanks
  the old column; `key_sha256` in the API stays).
- Coordination with #251: its entry screen writes through `UtubotSettings.setFilmsRealDebridToken` and
  `setFilmsAddonUrl`, which the sync wraps, so there is one storage model. Checkpoint 6 starts after #251 is merged or
  closed; if it is still open, checkpoint 6 rebases it first.
- Operations (owner's pipeline, tracked outside this repository): the master key is created on the server host and kept
  in the owner's password store; a database backup is useless without it and the restore test covers both.

## 7. Migration of today's TV values

1. The first sync of a device (`migrated_at` empty) is `initial: true`. Before it sends anything, the TV writes a copy
   of every synced preference to `utubot_settings_pre_sync` (kept; one hidden action restores it).
2. The TV sends every synced key it has (`base_rev` 0), set or default, with a flag for "the user set it".
3. For each key the server compares with the value it would resolve for this TV. Equal: nothing is stored. Different
   and set on the TV: the TV's value becomes this TV's override (`via: migration`). The TV's real behaviour wins over
   a web value that never had an effect, so nothing changes on the screen.
4. The answer is the resolved document; it now equals what the TV had. The TV stores the `rev`s and `migrated_at` is
   set. A second `initial` from the same device is treated as a normal sync.
5. The web page then shows, per TV, "This TV has its own value" for each migrated difference, with "Use my default"
   and "Use for all my TVs". Web values of the old "TV settings" card stay as the user's values.
6. Secrets do not migrate silently (section 6, D2). Device-only keys and local state are not sent.

## 8. Clients (parity)

- TV app: `UtubotSettingsSync` (pull, apply, outbox, first sync), a status line at the top of AI features ("Synced with
  Family server, 2 min ago" or "Not synced: the server does not answer. Changes are kept on this TV"). Hooks in
  upstream files are listed in `ai/APP_INTEGRATION.md`.
- Browser extension: the same device channel and schema (keys with `clients` containing `extension`); this replaces
  the wording of companion step C3 in `ai/BROWSER_EXTENSION_PLAN.md`. Until the extension reaches that step, checkpoint
  1 adds the matrix row `settings-sync`: "TV: settings follow the server (`UtubotSettingsSync`) | `GET/POST
  /v1/device/settings`, `GET /v1/settings/schema` | Options page values follow the server; local until C3 | Same".
- Voice consent, the default prompt and the models are already server-side and need no client change.

## 9. Checkpoints

Each checkpoint is one pull request with tests, the contract change that goes with its wire change, and a DEVLOG entry.
A checkpoint is not started before the one above it is merged. The MVP is checkpoints 1 to 4.

| # | Checkpoint | Main files | Done when |
|---|---|---|---|
| 1 | **Schema and inventory guard.** `ai/settings/schema.json` with every key of sections 2.1 to 2.3; loader and validator; `GET /v1/settings/schema`; contract addendum; matrix row; the `mark_only` finding | `ai/settings/schema.json`, `ai-backend/src/utubot/settingsschema.py`, `app.py`, `ai/CONTRACT.md`, `ai/BROWSER_EXTENSION_PLAN.md` | Tests T1 pass. No behaviour changes |
| 2 | **Server store and device channel.** Tables of 4.2, resolver, the routes of 4.3, audit, status, `[settings_sync] enabled` (default false), mock backend routes | `settings.py`, `devicesettings.py`, `db.py`, `config.py`, `scripts/emulator_mock_backend.py`, docs | Tests T2 pass; a database from before opens with its data |
| 3 | **TV sync for the AI keys.** `UtubotSettingsSync`, outbox, first sync with the copy, status line, the delay entry accepts any value in range | `common/.../utubot/UtubotSettingsSync.java`, `UtubotSettings.java`, `UtubotSettingsPresenter.java`, `UtubotClient.java`, `UtubotParser.java`, `ai/APP_INTEGRATION.md` | Tests T3 pass; emulator run against the mock backend in a network namespace with no route out |
| 4 | **Settings page (MVP).** Page, search, review-and-save, per-TV tab, chips, History; old card replaced | `web/ui/js/pages/settings.js`, `main.js`, `components.js`, `devices.js`, `app.css`, `capture.cjs` | Tests T4 pass; screenshots at 1440 and 390 px; MVP acceptance of section 11 on the owner's TV |
| 5 | **Per-TV settings and speed.** The keys of 2.2 and the `tv` rows of 2.1, `updates.checks` obeyed, "Copy from another TV", long poll | schema, `UpdatesSettingsPresenter.java`, `UtubotUpdateSchedule.java`, `devicesettings.py`, `settings.js` | Tests T5 pass; web to TV under 3 s |
| 6 | **Secrets (#276).** Section 6 complete, provider key moved | `secrets.py`, `userproviders.py`, `cli.py`, `account.js`, `UtubotSettingsSync.java`, `UtubotFilmsPresenter.java` (from #251) | Tests T6 pass; closes #276 except the IMDb part |
| 7 | **Live push and the extension.** `settings` frame on the live server (after voice checkpoint 3); the extension follows the server (C3) | `realtime/`, `extension/src/background/` | Web to TV under 1 s with the live server; extension e2e |
| 8 | **Full TV settings.** Generated inventory of the inherited settings, then a plan revision (whole-TV backup and restore first, chosen keys in the schema after) | this file | The owner accepts the revised plan |

## 10. Tests

No test contacts YouTube, a real model or any outside service. Backend: `uv run pytest` in `ai-backend/`. App: `:common:testStutubotDebugUnitTest`
with the local test server already used by `UtubotClientTest`. Web: the Playwright capture against the mock backend.

- **T1 (schema):** the file validates; every key has a title, a description, a type, a default inside its range and a
  scope; every field of `settings.SECTION_FIELDS` maps to exactly one key and back; an app unit test reads the `KEY_*`
  constants of `UtubotSettings` and fails unless each is a `tv_pref` of the schema or in the explicit device-only list
  of section 2.4 (a new preference cannot be added without classifying it).
- **T2 (server):** resolution order for each of the 6 levels; a device override does not leak to another device or
  user; `base_rev` equal, lower and for an unknown key; every write makes exactly one audit row and raises the version
  by one; two writers from one version: one wins; `initial` twice; a key above the client's schema is not sent; routes
  answer `404` with the switch off and `/v1/me`, `/setup.json` and the old document are byte-identical for an old
  client; audit pruning at 5,000 rows and 180 days.
- **T3 (TV):** a pulled value reaches the getter and fires the existing listeners (panel switch); a local change is
  applied before any network call; 50 offline changes of one key make one upload; the outbox survives a restart; a
  `superseded` answer applies the server value and shows the message once; server down, `404`, `401`, timeout and bad
  JSON leave every value as it was; first sync with every synced key set to a non-default value: all N of N values are
  the same after it, and the copy exists; no sync call on the main thread.
- **T4 (web):** DOM tests of the page (`tests/js`): search by title, description and key; staging, review, discard;
  `409` keeps staged changes; chips for applied, waiting, own value and old app; History rows; no sideways scroll and
  no console error at 390 and 1440 px.
- **T5:** the long poll answers within 1 s of a change and with "unchanged" at `wait_ms`; `updates.checks` off stops
  the timer and leaves the manual check; copying a TV stages only `rw` keys.
- **T6 (secrets):** a canary value is stored, then every response body, log record, audit row and the raw database
  file are searched for it: 0 hits; a changed ciphertext, nonce or user fails to decrypt; user B gets `404` for user
  A's secret and never sees its `last4`; no master key gives `503` and stores nothing; rotation keeps every value;
  the provider-key migration keeps `key_sha256`; a browser session cannot call the device secrets route.

## 11. Acceptance (numbers)

| What | Target | How it is measured |
|---|---|---|
| Web change reaches a TV that is open (MVP) | 95% within 35 s, all within 65 s | 20 saves on the owner's TV, time from Save to the "Applied" chip |
| Same, after checkpoint 5 / 7 | 95% within 3 s / within 1 s | as above |
| TV change is visible on the web | within 5 s when online | 10 changes |
| "Applied" chip after the TV applied | within 5 s | page poll of 5 s |
| TV start with the server down | 0 ms added to the start; 100% of settings as before | unit test and one emulator run with the mock backend stopped |
| First sync | 0 values lost or changed on the TV (N of N keys) | T3 matrix and the owner's TV: values listed before and after |
| Unchanged sync answer | at most 300 bytes; handler under 10 ms at the 95th percentile over 1,000 calls | backend test |
| Audit | 1 row per change, 100% of changes | T2 |
| Secrets in responses, logs, audit, clear text in the database | 0 | T6 canary |
| Unclassified TV preferences | 0 | T1 |
| Settings reachable from the web | MVP: every row of 2.1 marked MVP; checkpoint 5: every `rw` row of 2.1 and 2.2 | checklist against section 2 |
| Search | every setting found by its title, a word of its description and its key | T4 |
| Web UI | no sideways scroll, no console error at 390 and 1440 px | capture script |

## 12. Rollback

- Server: every table is new (`CREATE TABLE IF NOT EXISTS`) and no existing column changes before checkpoint 6, so an
  older backend opens the database unchanged. `[settings_sync] enabled = false` removes the routes and
  `features.settings_sync`; TVs then keep their last values and stop syncing. User values written through the document
  stay where they always were (`policy_overrides`).
- TV: an app release without the sync reads the same preferences, which hold the last applied values. The copy of
  step 7.1 restores the values from before the first sync. Device overrides stay on the server for the next try.
- Web: the Settings route is removed and the old "TV settings" card comes back with one revert; no data moves.
- Secrets (checkpoint 6): the provider-key migration keeps a copy of the old column in a table
  `user_providers_pre_secrets` until `utubot secrets check` has passed on the live server; the revert restores from
  it. A lost master key cannot be recovered: the user types the secrets again, and the TVs keep their own copies until
  then. The TV's own Real-Debrid entry stays as the fallback in every case.

## 13. Risks

- A wrong remote value locks the owner out of a TV: the address, the token and the update address are never synced
  (2.4), and development mode and the assess switch ask for confirmation.
- Two sources of truth creep back: T1 fails the build for a setting outside the schema.
- The 30 s poll costs requests: one small request per open TV; the long poll of checkpoint 5 replaces it.
- TV clocks: no rule depends on them (4.4).
