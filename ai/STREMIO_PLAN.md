# Stremio library import: watchlist and continue watching (plan)

Status: draft 1, 28 November 2026. Checkpoint r0 imports the owner's Stremio watch state into the u·tubot films store (backend + web UI; the TV reads the store). A two-way sync is a later investigation, not part of r0.

Related: owner issue #308 (bring the owner's Stremio watchlist and continue-watching into u·tubot films), `ai/CONTRACT.md` ("Clients", secrets, the films store), `ai/WEB_SETTINGS_PLAN.md` (accounts and services), `ai/BROWSER_EXTENSION_PLAN.md` (parity), `ai-backend/DEVLOG.md`.

---

# Part 1: owner plan

## What changes for you

- Under **Accounts and services** on the web **Settings** page there is a **Stremio** card.
- You sign in with your Stremio email and password. The server does it once, keeps only the auth key it gets back (encrypted, like the Real-Debrid token), and never keeps or shows your password.
- After you sign in, the server reads your Stremio library and copies it into u·tubot films: the titles in your Stremio watchlist become your **My list**, and where you stopped becomes **Continue watching**. Watched marks come too.
- A button imports again whenever you ask for it, and the server refreshes it once a day. The card says how many titles came in and how many it could not match to a film.
- It works on the TV too: your My list and Continue watching rows are filled from what the server imported.
- Only the import is here. Making the TV's own progress go back into Stremio is a later question, not this.

## Order of the work

1. **First usable step (r0):** the server signs in, keeps the auth key, reads the library, maps it to films, and the web page shows the counts. The TV reads the filled store.
2. **Then:** the TV gets its own **Import** button and shows the counts, so a viewer can refresh without the web page.
3. **Later:** a two-way sync, so what you watch on the TV also updates Stremio. This needs a decision about which side wins and is a separate investigation.

## Decisions needed from you

| # | Question | Recommended |
|---|---|---|
| D1 | Does the server keep your Stremio key, or does the TV? | The server. It stays server-side only, encrypted, and never goes to the TV (like the Real-Debrid token). The TV just reads the films the server imported. |
| D2 | What if a Stremio title has no IMDb id (an old or local title)? | The server counts it as "not matched" and tells you how many there are; it does not fill a row it cannot place. |
| D3 | How often should the server refresh? | On demand (your button) plus once a day. No import runs without the server already having your key. |

---

# Part 2: agent plan

## 1. Facts checked (28 November 2026, `main`)

| Fact | Where |
|---|---|
| The owner wants their Stremio watchlist and continue-watching in u·tubot films (`#308`) | owner issue, quoted in the task |
| The films store is per-user on the backend; the TV only reads it and shows the rows | `ai/CONTRACT.md` (the films store), `UtubotFilmsCatalog`, `FilmsHomeActivity` |
| Stremio login is `POST https://stremio.com/api/auth` with `{"event":"login","payload":{"email","password"}}`; it returns `{"status":"OK","auth":"<key>"}` | Stremio API |
| The library is `GET https://lib.stremio.com/api/datastoreGet?payload=<base64>&auth=<key>` with `payload` = base64 of `{"op":"read","key":"libraryItem"}`; the answer is double-base64 `{"payload":"<base64>","signature":"..."}` | Stremio API |
| A `libraryItem` key is a movie IMDb id (`tt0944947`) or an episode (`tt0944947:1:2`); it carries `timeOffset` (seconds), `watched {"S1E2": fraction}`, `watchedAnyway {"S1E2": true}` | Stremio library shape |
| A title counts watched at 90% of the running time | `UtubotFilmsProgress.WATCHED_SHARE = 0.9` (already on the TV) |
| Accounts and services are server-side secrets on the web Settings page; the key is not delivered to the TV | `ai/WEB_SETTINGS_PLAN.md`, `ai/CONTRACT.md` ("Clients") |
| Every feature is built for the TV app and the web UI; the extension row is its parity matrix | `ai/CONTRACT.md` ("Clients"), `ai/BROWSER_EXTENSION_PLAN.md` |

## 2. Decisions

- **D4. The auth key stays server-side.** It is stored via the secret store as `films_stremio_auth` and never goes to the TV and never enters the settings schema. The TV calls the import endpoint; it never sees the key. This matches the owner rule "the server keeps only the auth key."
- **D5. The web login is a dedicated card, not the generic secret row.** The generic "Accounts and services" row holds one-token secrets (Real-Debrid, add-on address). Stremio needs email + password, then the server stores only the returned key, so it is its own card that signs in, imports and shows counts.
- **D6. Mapping is one import per library item.** A movie becomes one films entry (id = IMDb id, position from `timeOffset`, not watched). A series episode becomes an entry (id = `imdb:season:episode`, watched when fraction ≥ 0.9 or in `watchedAnyway`); the series also gets a resume entry from its `timeOffset`.
- **D7. Unmapped is counted, not guessed.** A key that is not `tt\d{5,10}` (movie) or `tt\d{5,10}:s:e` (episode) is counted as unmapped and shown as a number; no row is created for it.
- **D8. r0 is import only.** No write back to Stremio. The two-way sync is a later investigation with its own decision (D3).

## 3. Files (backend; clients where named)

| File | Change |
|---|---|
| `ai-backend/src/utubot/config.py`, `config.example.toml` | `[films.stremio]` config (endpoints, timeouts) |
| `ai-backend/src/utubot/urlguard.py` | `guarded_request`: validated request with a size cap and query merge, for the two Stremio hosts |
| `ai-backend/src/utubot/stremio.py` (new) | login, library read, and the library-to-films mapping |
| `ai-backend/src/utubot/stremio_routes.py` (new) | `POST /v1/films/stremio/login`, `POST /v1/films/stremio/import`, `GET /v1/films/stremio/status` |
| `ai-backend/src/utubot/app.py` | wire the routes and the Stremio transport |
| `ai-backend/src/utubot/web/ui/js/pages/settings.js` | the Stremio account card (sign in, import, counts) |
| `ai-backend/tests/test_stremio.py`, `ai-backend/tests/js/settings.test.mjs` | backend and web-UI tests |
| `ai/CONTRACT.md` | the three new endpoints, the `films_stremio_auth` server-side secret |

## 4. Feature-parity matrix

The Stremio import is a **TV + web UI + backend** feature. The browser extension shows no films section (films are IMDb titles, not YouTube videos), so its row is "Not applicable", as the contract's "Clients" section allows for TV-only stores.

| Feature | Backend | TV app | Browser extension |
|---|---|---|---|
| `stremio-import` | `POST /v1/films/stremio/login`, `POST /v1/films/stremio/import`, `GET /v1/films/stremio/status` | The My list and Continue watching rows are filled from the imported store; an Import button and the counts (see r0 checkpoint 2) | Not applicable: the watchlist and continue-watching rows are the TV's films store (IMDb films, not a YouTube video). The extension shows no films section. In the contract's "Clients" section | Not applicable |

## 5. Checkpoints

Each ends with `uv run pytest -q`, `ruff check`, `ruff format --check`, and a pull request. The backend tests use recorded fixtures and the mock backend; none contacts Stremio, YouTube or any real service.

| # | Content | Done when |
|---|---|---|
| r0 | Backend: login keeps the auth key (server-side), the library read, the mapping, the three routes, the web card; contract + config + docs | the owner's library maps to My list + Continue watching with the right watched marks; unmapped is counted; the web card signs in, imports and shows the counts; `ai/CONTRACT.md` updated |
| 1 | TV: an Import button on the films home and the counts on the card; the TV triggers `POST /v1/films/stremio/import` and reads the rows | emulator check with the mock backend; the row fills and the count shows |
| 2 | Two-way sync investigation: which side wins, when to write back | a short note with the decision; not built in r0 |

Tests named now: `test_stremio.py` (login success and failure, the library read, the mapping of a movie, a series with watched episodes and a resume offset, unmapped keys), `settings.test.mjs` (the card signs in, imports and shows the counts; a connected account shows the Import button; a login failure keeps the form).

## 6. Verified, and not

### 6.1 Verified (r0)

- Backend unit tests pass (`ai-backend/tests/test_stremio.py`); `ruff check` and `ruff format --check` clean.
- Web-UI tests pass (`ai-backend/tests/js/settings.test.mjs`): the card signs in, imports and shows the counts; a connected account shows the Import button; a login failure keeps the sign-in form and shows the server message.
- The auth key is stored server-side and never delivered to the TV or added to the settings schema.

### 6.2 Not yet

- The TV Import button and counts (checkpoint 1).
- A two-way sync (checkpoint 2, investigation).
