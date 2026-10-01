# Build Log — Outrun the Police

Running log of decisions, progress, and blockers. Newest entries at the top.
Every session (Claude Code, Gemini, or Rudra manually) should add an entry
when it makes a nontrivial decision or finishes a milestone — this file is
the single source of truth for "what's actually been done" across tools and
sessions, since context resets between them.

Format per entry:
```
## YYYY-MM-DD HH:MM (who/what session)
- What was done
- Decisions made (and why)
- What's broken / left for next session
```

---

## 2026-09-30 (Claude Code — Milestone 4: team frontend)
- Milestone 4 DONE: team-facing frontend, `game/templates/team.html`, served
  by new `GET /team` in `game/app.py`. No frontend framework/build step —
  plain HTML + vanilla JS `fetch`, one external CDN script (vis-network, for
  the graph render only), matching the admin panel's existing stack.
- Backend additions needed to support it (`game/app.py`):
  - `GET /api/team/<team_code>/history` — the per-team read endpoint PRD
    8.2 asks for ("personal submission history, their own attempts only").
    Didn't exist before this session; checked first, confirmed missing, then
    added it. Scoped by a single `WHERE team_code = ?` — no auth beyond
    knowing your own code, same trust model as `/api/submit_route` itself
    (PRD's "codes only, no passwords" default). Verified TEAM1 and TEAM2
    histories are fully isolated (curl'd both after seeding each with
    different routes — each only ever saw its own rows).
  - `GET /api/graph.json` / `GET /api/graph.csv` — plain static download of
    the actual Milestone-1-generated files via `send_from_directory`, not a
    re-serialization. Verified byte-identical (`diff`) against
    `game/graph.json` / `game/graph.csv` on disk.
  - `GET /team` — serves the page, no server-side auth (matches `/admin`'s
    pattern: the page is static, real access control is that a team can
    only ever query/submit under its own code).
- Team login: team code only, no password, per PRD 8.2/functional spec —
  the code is stored in `localStorage` client-side purely so the page
  remembers it on reload, not used for any auth beyond being the `team_code`
  value sent to already-open endpoints.
- Graph view: renders `GET /api/graph` exactly as returned — no client-side
  recomputation of `open_now`/`compromised`, matches the instruction. Node
  colors: green = HIDEOUT, red = EXTRACTION, amber = compromised, using the
  API's own `g.hideout`/`g.extraction`/`n.compromised` fields directly.
  Closed-now edges rendered faded/thin rather than removed, so teams can see
  the whole map (consistent with why `/api/graph` never strips closed
  edges). Plain JSON/CSV download links sit next to the graph and work
  independently of vis-network loading — verified by reading the HTML: the
  download `<a>` tags aren't inside any JS-gated block, and `showFallback()`
  only ever swaps the graph canvas for a text notice, it never touches the
  downloads or the submission form.
- Submission form: posts `{team_code, route}` to `/api/submit_route`
  exactly as Milestone 2 defined it, renders `accepted`/`reason`/
  `breakdown`/`is_new_best` directly from the real response — no
  reformatting of the reason string, so a rejection reason is shown to
  teams verbatim (e.g. `"no edge from N00 to N59"`, `"N15 is compromised"`),
  which matters since PRD 8.5 requires rejections to always carry a clear
  reason string.
- History table reads the new `/api/team/<code>/history` endpoint, newest
  first, shows route/status/score/event-time per row.
- No leaderboard on this page — confirmed intentional per PRD §11 default 5
  (admin-only) and the explicit instruction; `/api/leaderboard` stays
  admin-token-gated and untouched.
- Visual theme ("Money Heist"-inspired, not a reproduction — no mask/logo
  assets used, original layout/palette only): near-black background
  (`#0c0c0d`/`#171415` panels), red `#c81e1e`/`#ff3b3b` as primary/bright
  accent, amber `#d99a2b`/`#f5b942` for compromised-state and secondary
  accents, off-white text `#f2ece7`. Headings: Google Fonts **Oswald**
  (condensed/industrial, free, loaded via `<link>` not hotlinked from
  elsewhere). Body/data text: **IBM Plex Mono** (monospace, chosen over a
  plain sans so route lists / node IDs / scores stay legible and
  columnar — data-under-time-pressure legibility over vibe, per the
  instruction). Event clock rendered as a countdown-style readout
  (`T+MMM:SS`) in a black box with amber border rather than a plain number.
  Accepted submissions get a green-bordered panel headlined "JOB'S DONE —
  ROUTE ACCEPTED"; rejections get a red-bordered panel with a brief pulse
  animation headlined "BLOWN — ROUTE REJECTED" — but the actual
  `reason`/breakdown text underneath is always the literal, unstyled string
  from the API, so the mission-outcome framing never obscures what actually
  happened (explicit instruction: style must never cost clarity on pass/
  fail). These exact palette/font values are recorded here so `admin.html`
  can be reskinned to match later if Rudra wants visual consistency —
  admin.html was **not** touched this session.
- **Actually tested against the real server** (`ADMIN_TOKEN=test-token`,
  fresh `game.db`, port 5050):
  - `GET /team` → 200. `GET /api/graph.json` → 200, byte-identical to
    `game/graph.json` on disk (`diff`, exit 0). `GET /api/graph.csv` → 200,
    byte-identical to `game/graph.csv`. Content-Type headers confirmed:
    `application/json` and `text/csv; charset=utf-8`.
  - Submitted TEAM1's known-good route (`N00→N15→N30→N45→N59`) → accepted,
    breakdown `time=35 risk=8 cost=22 score=78.0`, `is_new_best: true` —
    matches Milestone 2's already-verified reference numbers exactly (no
    drift from reusing the same solver path).
  - Submitted TEAM1 an invalid route (`N00→N59`, no direct edge) →
    rejected, `reason: "no edge from N00 to N59"` — exact string the
    frontend's rejection panel would render verbatim.
  - Submitted TEAM2 a different route (`N00→N03→N07→N59`, the known trap
    route) → accepted, `score=235.0`.
  - **Isolation check (the thing most likely to leak)**: `GET
    /api/team/TEAM1/history` → exactly TEAM1's 2 attempts (1 accepted, 1
    rejected), TEAM2's route nowhere in the response. `GET
    /api/team/TEAM2/history` → exactly TEAM2's 1 attempt, none of TEAM1's
    rows. `GET /api/team/NOBODY/history` (team that never submitted) →
    `[]`, no error. Confirms the new endpoint is genuinely team-scoped, not
    just filtered client-side.
  - `GET /api/graph` shape checked field-by-field against what
    `team.html`'s JS actually reads: `nodes[].id`/`.compromised`,
    `edges[].id/from/to/time/risk/cost/window_start/window_end/open_now`,
    top-level `hideout`/`extraction`/`event_time`/`compromised_nodes` — all
    present and correctly typed, confirmed by admin-compromising N15 live
    and re-fetching `/api/graph`: `N15`'s node object flipped to
    `compromised: true` and appeared in `compromised_nodes`, matching
    exactly what the renderer keys off. Uncompromised it after.
  - Malformed submission (missing `team_code`) → 400
    `{"error": "team_code is required"}`, same as Milestone 2, unchanged.
  - Cleaned up: killed the test server, deleted the test `game.db`.
- **Testing caveat, same as the admin-panel session**: the Claude-in-Chrome
  browser extension is still not connected in this environment
  (`tabs_context_mcp` → "Browser extension is not connected"), so **no
  actual click-through/visual render check happened this session** — not
  for the graph rendering, not for the color/contrast/font choices, not for
  mobile/narrow-width behavior. Everything above is real API-level and
  response-shape verification (the JS was read against confirmed real
  response fields, not assumed), which proves the data flow is correct, but
  it does **not** prove vis-network actually renders correctly in a live
  browser, that the fallback text-notice path visually triggers correctly
  if the CDN script fails to load, or that the red/amber palette is
  actually legible at a glance in a bright event hall. **Recommend an
  actual browser click-through before the event** — open
  `http://127.0.0.1:5050/team` manually (or once the Chrome extension is
  connected), test login, watch the graph actually render, submit a real
  route and confirm the accept/reject panels look right, and eyeball
  contrast on a laptop screen under normal room lighting.
- What's broken / left for next session:
  - Nothing known-broken from what could be tested via API.
  - Visual/UX confirmation in an actual browser is the main open item (see
    caveat above) — do this before the event, not after.
  - `admin.html` still uses its original plain styling, not yet reskinned
    to match — optional, only worth doing if Rudra wants visual consistency
    across both pages (palette/fonts recorded above for exactly that).
  - Milestone 5 (end-to-end test with fake teams simulating the
    `context.md` live-event walkthrough) not started.

## 2026-09-29 (Claude Code — cross-game integration session)
- Resolved PRD §11 Open Question 4 (compromise triggers) with Rudra:
  **auto-linking to other games is now real**, not just a stretch goal —
  built the integration surface the other four games call.
- **Auth decision**: one API key per calling game, issued by us, config'd
  as a `game_name -> key` map in `game/integration_auth.py` (env var
  `INTEGRATION_KEYS`, format `game3:key1,game5:key2`) — not hardcoded per
  route, not a single shared secret. Deliberately kept in one small module
  behind a single `require_game_key()` function (mirrors `require_admin()`
  in `app.py`) so if the event later builds a central cross-game gateway
  that issues one key for everyone (still being decided elsewhere), only
  this one file changes — no route code touches auth logic directly.
- **Compromise data model gained a second layer** — this is a schema
  change other sessions/branches need to know about (see note for the
  testing/deployment branch below):
  - Existing `compromised_nodes` table (global, admin-only) is **completely
    unchanged** — same schema, same `/api/admin/compromise` endpoint, same
    admin-panel toggle grid. Did not touch it.
  - New `team_compromised_nodes(team_code, node_id, set_by, set_at)` table
    in `game/db.py` — a per-team compromise list, additive alongside the
    global one.
  - New `db.effective_compromised(team_code)` = union of global +
    that team's per-team set. `/api/submit_route` now calls this instead
    of the old global-only `db.get_compromised()` — this is the one call
    site that changed in the existing submission path, everything else
    about validation is untouched (`solver.validate_path()` itself didn't
    need to change, it already took an arbitrary `compromised` set).
- Built (`game/app.py`):
  - `POST /api/admin/team_compromise` — admin-token-gated, same pattern as
    the existing global toggle but scoped to one `team_code`.
  - `GET /api/admin/team_compromised` — admin-token-gated, lists every
    active per-team compromise (for the panel's per-team view).
  - `GET /api/integration/leaderboard` — game-key-gated, every team's best
    score + time/risk/cost breakdown + `has_valid_route`.
  - `GET /api/integration/result/<team_code>` — game-key-gated, one team's
    current best valid route + breakdown; 404 with `has_valid_route: false`
    if they don't have one yet.
  - `POST /api/integration/compromise-trigger` — game-key-gated,
    `{team_code, node_id, reason}` -> writes into the NEW per-team list.
    `set_by` records the calling game name + reason for audit
    (`"integration:game3:bad result"`), same as `set_by: "admin"` for
    manual toggles.
- Admin panel (`game/templates/admin.html`): added a second compromise
  section directly below the existing global grid, **styled amber/orange**
  vs. the global list's red, with its own heading "(Per-Team — this team
  only)" right next to "(Global — all teams)" on the original section —
  organizers can't confuse which is which at a glance. Simple
  team-code + node-id input + button to add, chip list with a "clear"
  button per entry to remove. Did not touch or restyle the existing global
  grid at all.
- Wrote `brain/API-CONTRACT.md` — the handoff doc for the other four
  games' developers. Documents all three integration endpoints' exact
  request/response JSON, the `X-Game-Key` header, and error shapes, written
  assuming zero familiarity with this codebase (no internal function/table
  names, just the HTTP contract). Also notes the auth-swap-to-gateway
  possibility so nobody's surprised if that header's meaning changes later.
- **Actually tested it live**, not just read the code (server on :5050,
  `ADMIN_TOKEN=test-token`, `INTEGRATION_KEYS=game3:g3key,game5:g5key`):
  - Seeded TEAM1 and TEAM2 both with the reference best-score route
    (score 78.0) via the normal `/api/submit_route`.
  - `GET /api/integration/leaderboard` with no key -> 401; wrong key ->
    401; correct key -> 200 with both teams, correct breakdown fields.
  - `GET /api/integration/result/TEAM1` with correct key -> 200, exact
    route + score match. `result/NOBODY` (team with no valid route) -> 404
    with `has_valid_route: false`.
  - `POST /api/integration/compromise-trigger` with no key -> 401.
    Correct key (`game3`), compromised `N15` for `TEAM1` only, reason
    `"bad game3 result"` -> 200. **TEAM1 resubmitted the exact same
    previously-accepted route -> rejected `"N15 is compromised"`.
    TEAM2 resubmitted the identical route in between -> still accepted,
    same score 78.0** — confirms the per-team block is genuinely isolated,
    not a global side-effect.
  - Confirmed the existing global list is untouched: admin-compromised
    `N30` globally -> TEAM2 (unaffected by the per-team block above) was
    then rejected too, exactly as global compromise has always worked.
    Uncompromised it after.
  - Admin per-team endpoints: `GET /api/admin/team_compromised` (no
    token -> 401; with token -> showed the live TEAM1/N15 entry with
    correct `set_by: "integration:game3:bad game3 result"`).
    `POST /api/admin/team_compromise` with `compromised: false` cleared
    it -> confirmed TEAM1 could then resubmit and be accepted again
    (score 78.0, matching before).
  - Malformed input: `compromise-trigger` missing `team_code` -> 400;
    unknown `node_id` -> 400. Same for `admin/team_compromise`.
  - Restart survival: killed and restarted the server mid-test, re-queried
    `/api/admin/team_compromised` (correctly empty, since TEAM1's entry had
    been cleared before restart) and `/api/integration/leaderboard`
    (both teams' scores intact) — new table persists to the same SQLite
    file, no special handling needed.
  - Re-ran `solver.py`'s self-check after all changes — still passes,
    confirms the shared validation core wasn't touched.
  - Cleaned up: killed the test server, deleted the test `game.db`.
- **Note for the teammate on the testing/deployment branch**: the
  compromised-node data model just gained a second layer
  (`team_compromised_nodes`, on top of the existing `compromised_nodes`
  which is unchanged). **Pull latest `main` before finalizing your own
  compromised-node test cases** — anything written against "compromise ==
  one global table" is testing the old shape. The thing to know: a node is
  now blocked for a team if it's in *either* table (`db.effective_compromised`
  in `game/db.py` is the one function that does this union — call that
  instead of re-deriving the union yourself if your tests need to compute
  expected-blocked state). Global-only compromise tests you already have
  should still pass unchanged since that table/endpoint didn't move.
- What's broken / left for next session:
  - Nothing known-broken from what was tested.
  - `INTEGRATION_KEYS` currently only comes from an env var with a dev
    fallback (`game3:dev-game3-key,game5:dev-game5-key`) baked into
    `integration_auth.py` — same caveat as `ADMIN_TOKEN`: **must** be set
    to real per-game secrets via env var before the event, don't ship the
    dev fallback live.
  - Milestone 4 (team-facing frontend) still not started — this session
    was integration-backend-only, per the actual instructions given (the
    "Milestone 4" label in the request didn't match PRD §12's Milestone 4;
    treated the explicit build list in the request as authoritative and
    flagged this here rather than silently building the wrong thing).

## 2026-09-28 (Claude Code — build session 3)
- Milestone 3 DONE: admin panel, built in `game/templates/admin.html`,
  served by a new `GET /admin` route in `game/app.py`.
- **Clock policy confirmed by Rudra and encoded in the UI, not just the
  API**: `action: set` ("set clock to minute X") is the primary, prominent
  control — big input + button, always-visible current `t` value.
  `start`/`pause` are present but styled as visually secondary
  ("(testing only)" labels, muted button style) and a hint line states
  outright not to rely on them during the live event. Matches how
  compromise events are already scripted/triggered live per
  `context.md`'s walkthrough (organizers jump state on cues, not let a
  free-running clock drive things). Also documented at the top of
  `app.py`'s docstring, not just in the UI.
- Single HTML page, plain server-rendered + vanilla JS `fetch` — no
  frontend framework, per the milestone instruction (this isn't the
  polished deliverable, the team frontend is).
- Auth: page itself has no server-side gate (it's static HTML/JS) — all
  real access control is the existing `X-Admin-Token`-gated API endpoints
  from Milestone 2. The page prompts for a token client-side, and "login"
  is literally just calling `/api/leaderboard` with that token and
  checking for a 200 vs 401/other — there's no separate/fake auth check,
  the same server-side gate from Milestone 2 is what's actually enforced.
  Wrong or missing token → real 401 from the server, shown as "Invalid
  token."
- Sections built: event clock (set + start/pause), compromised-nodes
  toggle grid (click any node chip to flip it), leaderboard (admin-only,
  refresh button), live submissions table (team/valid-or-not/reason-or-
  score/route/event-time, manual refresh + 5s auto-refresh toggle), export
  buttons (JSON and CSV, trigger a browser download via blob).
- **Testing caveat**: the Claude-in-Chrome browser extension was not
  connected in this environment (`tabs_context_mcp` returned "Browser
  extension is not connected"), so a real click-through in an actual
  browser window was not possible this session. Compensated by testing
  every underlying interaction at the API level — the exact calls each
  button/handler makes — and by re-reading the JS against the verified
  response shapes to confirm field names match (e.g. `n.compromised`,
  `row.best_score`, `row.route_json` all checked against real curl
  output, not assumed). This is real coverage of "does clicking the
  button do the right thing to the server," but it is not proof the DOM
  actually renders/updates correctly in a live browser — flag this to
  Rudra: **a real click-through in an actual browser is worth doing
  before the event**, ideally once the Chrome extension is connected, or
  just by opening `http://127.0.0.1:5050/admin` manually and clicking
  through.
- What was actually run and verified (server + curl, simulating each
  button's exact fetch call):
  - `GET /admin` → 200, serves the HTML page.
  - Login flow: `/api/leaderboard` with correct token → 200 (panel would
    show); with wrong token → 401 (error would show). Matches `login()`.
  - Node toggle: compromised N15 via the same call `toggleNode()` makes →
    confirmed `/api/graph` immediately reflects `compromised: true` for
    N15 (no reload) → confirmed a live route submission through N15 was
    then rejected with `"N15 is compromised"`. Uncompromised it after.
  - Clock: confirmed edge `E66` (window 52–101) is `open_now: false` at
    t=0, called `action: set, t: 60` (the primary UI action), confirmed
    `/api/graph` immediately showed `event_time: 60.0` and `E66` now
    `open_now: true`. Reset to t=0 after.
  - Submissions view: submitted one valid and one invalid route live,
    confirmed `/api/admin/submissions` (what `loadSubmissions()` polls)
    shows both, newest first, with correct valid/reason/score/route/
    event_t fields.
  - Leaderboard: confirmed `/api/leaderboard` shows the team's best score
    only (78.0), matching Milestone 2's verified scoring.
  - Exports: both `/api/admin/export` (JSON, `content-type:
    application/json`) and `/api/admin/export.csv` (CSV, `content-type:
    text/csv`) returned 200 with the same correct best-per-team data
    Milestone 2 already verified — confirms `exportResults()`'s blob-
    download flow has correct data and headers to work with.
  - Cleaned up: stopped the server, deleted the test `game.db`.
- Deviations / decisions:
  - No new auth mechanism — reused Milestone 2's header-based admin
    token exactly as instructed, rather than e.g. a login cookie/session.
    Simpler, and the whole event only needs one shared admin credential
    passed around to organizers/volunteers.
  - Auto-refresh interval: 5 seconds, arbitrary but reasonable for a live
    organizer-monitoring view without hammering the server; not specified
    in the PRD, no reason to make it configurable yet.
- What's broken / left for next session:
  - Nothing known-broken from what could be tested (see testing caveat
    above — recommend an actual browser click-through before the event,
    this session couldn't do one).
  - Per the explicit instruction: **not** starting the team-facing
    frontend (Milestone 4) without confirming with Rudra first — stopping
    here.

## 2026-09-28 (Claude Code — build session 2)
- Milestone 2 DONE: Flask + SQLite backend, built in `game/`.
- Dependencies: `pip install` into homebrew Python is blocked (PEP 668,
  externally-managed-environment). Created a project venv at `.venv/`
  instead of using `--break-system-packages` — the correct fix, not a
  workaround. `game/requirements.txt` pins `flask==3.1.3`. To run:
  `.venv/bin/python game/app.py` from repo root, or `cd game &&
  ../.venv/bin/python app.py`. `.venv/` and `game/game.db` added to
  `.gitignore`.
- `game/db.py` — SQLite schema and connection helper. Four tables:
  - `teams(team_code PK, name)` — auto-created on first submission from a
    new team code (registration-light per PRD's "codes only" default).
  - `submissions` — every attempt, valid AND rejected, with reason,
    time/risk/cost/score breakdown (null for rejected), submitted_at
    (wall clock) and event_t (event-clock minute at submission) — this is
    the admin's full audit log.
  - `compromised_nodes(node_id PK, set_by, set_at)` — presence in the
    table = compromised; simple toggle via INSERT OR REPLACE / DELETE.
  - `event_clock` — single-row table (id=1). Models running vs paused:
    when running, `current_event_t()` computes live elapsed time from
    `started_at` instead of storing a value that needs a background
    ticker/thread. Avoids any polling loop entirely — the clock is
    computed on read, which is simpler and correct on restart.
  - All state confirmed to survive a real `kill -9` + restart (see testing
    below) — satisfies PRD 8.4's "idempotent, replayable" requirement.
- `game/app.py` — Flask app, imports `validate_path`, `path_totals`,
  `path_score` directly from `game/solver.py` (not reimplemented, per
  claude.md and the explicit milestone instruction).
  - `GET /api/graph` — full node/edge list annotated with `open_now` per
    edge (live window check) and `compromised` per node, plus current
    `event_time`. Teams see the whole map always (so they can plan ahead
    of clock changes) rather than a graph with closed edges stripped out.
  - `POST /api/submit_route` — validates via `validate_path()` against
    live clock + compromised state at the moment of submission, scores
    with the weights from `logs.md`/`graph.json`, stores every attempt
    (valid or not), returns `is_new_best` so a team knows if a worse-but-
    valid resubmission actually improved their standing. Lower score is
    kept as "best" (lower = better, confirmed consistent with solver).
  - `GET /api/leaderboard` — admin-token-gated (PRD §11 default 5:
    admin-only visibility). Ordered by each team's best valid score, ASC.
  - Admin routes all gated on `X-Admin-Token` header vs `ADMIN_TOKEN` env
    var (default `dev-admin-token` for local dev — **must** be overridden
    via env var for the real event): `/api/admin/compromise` (toggle),
    `/api/admin/clock` (start/pause/set, with optional `keep_running` for
    set-while-live), `/api/admin/submissions` (full log), `/api/admin/export`
    and `/api/admin/export.csv` (best valid route per team, keyed by
    team_code — the exact Game 5 handoff artifact from PRD §8.3/§10).
  - Malformed submissions (missing team_code, non-list route) rejected
    with 400 before touching the DB. Unknown node IDs in admin/compromise
    rejected with 400.
- **Actually ran it end-to-end**, not just unit-level:
  - Started the real Flask dev server (`ADMIN_TOKEN=test-token`, port
    5050), curled every endpoint.
  - `GET /api/graph` at t=0: 60 nodes, 176 edges, nothing compromised,
    weights match `graph.json`. Confirmed.
  - Submitted the solver's reference best-score route
    (`N00->N15->N30->N45->N59`) → accepted, breakdown time=35 risk=8
    cost=22 score=78.0 — **exact match** to solver's reference output.
  - Rejection reason 1 (bad path): submitted `["N00","N59"]` (no direct
    edge) → rejected `"no edge from N00 to N59"`.
  - Rejection reason 2 (closed edge): admin-set clock to t=119, found an
    edge (`E66 N06->N42`, window 52–101) closed by then, submitted it →
    rejected `"edge N06->N42 not open at t=119.0"`. Reset clock to t=0.
  - Rejection reason 3 (compromised node): admin-compromised N15 (part of
    the already-accepted best-score route), resubmitted the *same* route
    → rejected `"N15 is compromised"`. Confirms PRD §11 default 3
    (grandfathering): the earlier acceptance stayed in the DB untouched;
    only the new submission was checked against new state. Uncompromised
    N15 afterward.
  - Live clock: `admin/clock action=start`, waited ~2s wall-clock, GET
    /api/graph showed event_time had genuinely advanced (~0.038 min) —
    confirms it's computed live, not just stored. Paused it after.
  - Auth: `/api/leaderboard` with no token and with a wrong token both
    returned 401. Correct token succeeded.
  - Best-score tracking: had TEAM1 submit the fast/risky trap route
    (score 235.0) *after* their good route (score 78.0) — response
    correctly said `is_new_best: false`, leaderboard still showed 78.0.
    Had TEAM2 submit only the trap route — leaderboard showed both teams
    correctly ordered ascending by score (78.0, then 235.0).
  - Admin submissions log: confirmed all 6 attempts (valid + rejected)
    present with correct reasons/scores.
  - Export JSON and CSV: confirmed each shows exactly one row per team,
    each row being that team's best (lowest-score) *valid* route — this
    is the literal Game 5 handoff artifact, verified correct.
  - Restart survival: found and `kill -9`'d the actual server process
    (not just the backgrounded shell job — first attempt's job-control
    tracking was unreliable, had to `lsof -ti:5050` to find real PIDs),
    restarted the server fresh, re-queried leaderboard and compromised
    state — both fully intact. This is the real test of "SQLite file,
    not in-memory only" from PRD §8.4, not just an assumption from
    reading the code.
  - Malformed input: missing `team_code` → 400, non-list `route` → 400,
    unknown node in admin/compromise → 400 with clear error.
  - Cleaned up: stopped the test server, deleted the test `game.db` so a
    fresh DB gets created on next real start (no test-team pollution in
    what ships).
- Deviations from PRD / decisions made:
  - PRD §8.4 says "rate-limit or de-duplicate spammy submissions if
    needed (nice-to-have)" — **not built**. Explicitly deferred: nothing
    in the milestone list called for it yet, and it's marked nice-to-have.
    Flag for later if venue WiFi + 15-30 teams causes spam in practice.
  - Event clock's "1 wall-second ≈ 1/60 event-minute" when running is
    just what `current_event_t()`'s straight elapsed-time math gives by
    default (started_at diff in real minutes = event minutes, i.e. 1:1
    real-time-to-event-time). That means a 120-minute event window means
    the clock takes 2 real hours to run start-to-finish if left on
    "start" the whole time. **This needs an explicit decision before the
    event**: either that 1:1 mapping is fine (event literally runs ~2hrs
    and the graph's `event_duration` should match the real submission
    window), or organizers will manage the clock manually via `action:
    set` rather than "start" (which is realistically how live compromise
    events already work per the context.md walkthrough — organizers jump
    the clock via admin panel, not let it free-run). Recommend the
    latter: treat `start`/`pause` as available but expect organizers to
    mostly use `set` on scripted cues. Not blocking, just flagging.
  - Leaderboard admin-only (PRD §11 default 5) implemented as-is — no
    public/delayed leaderboard built, matches "default, nice-to-have
    deferred."
  - Team auth stayed at "codes only" (PRD §11 default 6) — a team row is
    silently created on first submission with `name = team_code`; there's
    no registration endpoint yet because the PRD doesn't ask for team
    management UI in this milestone, just the data model + submission
    flow. If teams need to be pre-registered with real names before the
    event, that's a small addition to `db.py`/`app.py`, not built yet.
- What's broken / left for next session:
  - Nothing broken; all tested paths behave correctly.
  - Milestone 3 (admin panel UI) and Milestone 4 (team frontend) not
    started — this session was backend-only per the instruction not to
    start the frontend yet.
  - `ADMIN_TOKEN` currently only comes from an env var with a dev
    fallback baked into `app.py` (`dev-admin-token`) — fine for local
    testing, but **must** be set to a real secret via env var before any
    public/venue deployment. Don't ship the fallback value live.
  - Rate limiting/de-dup still not built (see above, deferred on
    purpose).
  - CORS not configured — if the frontend (Milestone 4) ends up served
    from a different origin/port than the Flask app, will need
    `flask-cors` or equivalent. Not needed yet since no frontend exists.

## 2026-09-28 (Claude Code — build session)
- Milestone 1 DONE: graph generator + reference solver, built in `game/`.
- `game/graph_gen.py` — generates the city map: 60 nodes (`N00`..`N59`),
  176 directed edges, saved to `game/graph.json` (source of truth) and
  `game/graph.csv`. Fixed seed (42) so the event graph is reproducible.
  Structure: a backbone chain guaranteeing HIDEOUT (`N00`) -> EXTRACTION
  (`N59`) connectivity for the whole event window, a deliberate 3-hop
  "express" trap route (very low time, very high risk), a deliberate
  4-hop "safe" alternate route (moderate time, low risk/cost), plus 110
  random edges for density/red-herrings (some with narrow/early-closing
  windows).
- `game/solver.py` — reference solver: Dijkstra by time, Dijkstra by score
  (using published weights), a shared `validate_path()` that is meant to be
  imported directly by the future Flask backend (not reimplemented) so
  validation logic has one source of truth per claude.md's server-side-only
  rule. Self-check proves: graph solvable at t=0, fastest-by-time route and
  best-by-score route genuinely differ, best-by-score route scores strictly
  better despite being slower, compromised-node rejection works.
- **Actually ran it**, didn't just eyeball the code:
  - `python3 graph_gen.py` → 60 nodes, 176 edges generated.
  - `python3 solver.py` → self-check passed. Fastest route `N00->N03->N07->N59`
    (time=3, risk=57, cost=8, score=235.0) vs best-scoring route
    `N00->N15->N30->N45->N59` (time=35, risk=8, cost=22, score=78.0). Trap
    confirmed: 12x faster route scores 3x worse.
  - Re-ran `build_graph()` + self-check across 5 more random seeds (1, 2, 3,
    99, 1000) to confirm the trap isn't a lucky one-off of seed 42 — all
    passed.
  - Extra manual checks against the real `graph.json`: nonexistent edge
    rejected, unknown node ID rejected, edge queried outside its
    availability window rejected with correct reason string, HIDEOUT->
    EXTRACTION reachability sampled at t=0/30/60/90/119 (all reachable).
- Decisions made (per claude.md: proceed on PRD defaults, log them):
  - Directed edges, shared single graph for all teams — per PRD §11
    defaults 1 and 2.
  - Scoring weights: `time=1.0, risk=4.0, cost=0.5`, lower-is-better. Chose
    risk-heavy weighting specifically so the express trap route is
    punished hard — this is what makes the trap work, not arbitrary.
    These weights must be published in the event rules verbatim once
    finalized (PRD §8.5) — currently only live in `graph.json["weights"]`.
  - Event duration modeled as 120 minutes; all backbone/trap/safe edges
    open the entire event so the "always solvable" guarantee holds
    regardless of clock state, while the 110 random edges carry
    realistic/narrower windows for closure drama.
  - Stdlib-only implementation (heapq, json, csv, random) — no networkx/
    numpy. Keeps the "lightweight stack" constraint from claude.md and
    there's nothing here a 40-line Dijkstra doesn't already cover.
- What's broken / left for next session:
  - Nothing broken. Milestone 1 complete and verified.
  - Milestone 2 (Flask + SQLite backend: data model, graph state endpoint,
    submission validation + scoring) is next per PRD §12. It should
    **import `validate_path()` and `dijkstra`/scoring helpers from
    `game/solver.py`** rather than reimplementing — that's why solver.py
    was written as an importable module, not just a CLI script.
  - Not yet done: SQLite schema, compromised-node live state, event clock
    state, Flask routes, admin panel, frontend — none of this started.
  - Open Questions 3–6 from PRD §11 (lock-in behavior, compromise
    triggers, leaderboard visibility, team auth) still just have their
    stated defaults; not yet confirmed with Rudra, not yet blocking.

## 2026-09-28 (Claude — planning session, claude.ai)
- Read the CODEVERSE 2.0 brief (CODEVERSE_2.docx). Confirmed Rudra owns
  Phase 2, Game 4 — "Outrun the Police" (graph algorithms/optimization).
- Talked through the full game flow and a live-event example with Rudra;
  agreed narrative and mechanics (see `context.md`).
- Wrote `PRD.md`, `context.md`, this `logs.md`, `claude.md`, `gemini.md`.
- Did NOT write any application code yet — next step is handing this brain/
  folder to Claude Code (running inside Antigravity) to scaffold and build.
- Open questions logged in PRD §11 — needs decisions early in the build
  session, defaults are stated so the build isn't blocked, but confirm with
  Rudra if time allows.
- No graph generated yet, no backend scaffolded yet, no frontend started.

### Next session should:
1. Read `PRD.md` and `context.md` fully before writing any code.
2. Resolve or confirm-by-default the Open Questions (PRD §11).
3. Start with the graph generator + reference solver (Milestone 1) — this
   validates the whole game is fair/solvable before any web code is written.
4. Update this file after every milestone.
