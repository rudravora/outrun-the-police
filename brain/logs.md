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

## 2026-10-02 (Claude Code — real central gateway integration)
- **New scope, confirmed by Rudra**: implement the actual CODEVERSE 2.0
  central gateway integration per `brain/GATEWAY-INTEGRATION-SPEC.md`
  (saved verbatim — Rudra pasted it after an initial request referenced it
  before it had actually been attached; saved first, built against it
  second, per the instruction). This **supersedes** the direct
  game-to-game `/api/integration/*` endpoints from the 2026-09-29 session
  — per the spec, "games never call each other," everything goes through
  the gateway. Left the old endpoints running (not deleted, other games
  may be mid-switch) but nothing new is built on that path — see the
  superseded notice added to the top of `brain/API-CONTRACT.md`.
- **Key facts taken as given** (per the request, already confirmed with
  the gateway owner, overriding the spec doc's own `T01`/`T07`/`T00`
  example codes): our existing `team_code` IS the gateway's `team_id`,
  no mapping table. Our `game_id` is `"p2g4"`.
- **The real base URL/API key/test team T00 are not shared yet** (spec
  §6 timeline, still `<date>` placeholders) — built and tested entirely
  against a local mock (`game/gateway_mock.py`), with the real values as
  swappable env vars (`GATEWAY_BASE_URL`, `GATEWAY_API_KEY`). **Nothing
  here has touched the real gateway** — that's still to come once Rudra
  gets the real values.
- **`game/gateway_client.py` (new)**: the one module that talks to the
  gateway, per spec §2's global rules.
  - `send_event(event_type, team_id, points=0, money_delta=0, risk=None,
    meta=None)` — builds the event body exactly per spec §3A
    (`event_id` uuid4, `game_id`, ISO-UTC `timestamp`, the rest as given),
    POSTs to `/api/events` with `X-Game-Key`, 3s timeout. **Never raises**:
    any failure (not configured, timeout, connection error, non-2xx)
    queues the event into a new `gateway_outbox` SQLite table
    (`game/db.py`) instead — a submission can never fail because the
    gateway is unreachable, per spec §2 rule 6. A `409` (duplicate
    `event_id`) is treated as success per spec §2 rule 4/§2 rule 9, not
    an error.
  - `get_team_state(team_id)` — GETs `/api/teams/{id}/state`, same
    header/timeout, returns the parsed dict on success or `None` on ANY
    failure. Callers decide their own fallback; this function never
    raises into request handling.
  - `drain_outbox_once()` + `start_drain_thread()` — a single simple
    daemon thread, retries every `GATEWAY_DRAIN_INTERVAL` seconds
    (default 15, spec's 10-30s range), blind-retries every pending outbox
    row since retries are idempotent (spec §2 rule 4) — on success marks
    delivered, on failure just bumps the attempt counter and leaves it
    queued for next cycle. Deliberately simple (no backoff/pooling) since
    this is a handful-of-events-per-minute workload, not high-throughput.
  - **No-op when unconfigured**: if `GATEWAY_BASE_URL`/`GATEWAY_API_KEY`
    are unset, `send_event` only queues locally (never calls out) and
    `get_team_state` always returns `None` — confirmed local dev/testing
    without any gateway configured still works exactly as before this
    session (tested below).
  - `SEND_WRONG_ATTEMPTS` config flag (env var, default `false`) — see
    the open question below.
  - Used **stdlib `urllib.request`** instead of adding the `requests`
    dependency (checked: not already installed, `game/requirements.txt`
    only pins Flask) — two simple JSON-in/JSON-out calls with a timeout
    don't need a new dependency per claude.md's lightweight-stack rule.
- **`game/db.py`**: new `gateway_outbox` table (`event_id` PK, `body_json`,
  `created_at`, `delivered`, `delivered_at`, `attempts`,
  `last_attempt_at`) plus `outbox_enqueue`/`outbox_pending`/
  `outbox_mark_delivered`/`outbox_mark_attempt` helpers. `INSERT OR
  IGNORE` on enqueue so re-queuing the same `event_id` is a no-op,
  matching the gateway's own idempotency. New `route_code TEXT` column on
  `submissions` (see route-code feature below). **Did not** add a
  gateway call inside `db.effective_compromised()` itself — kept that
  function as the pure two-table (global + per-team admin/integration)
  union it already was, to avoid a circular import
  (`gateway_client.py` imports `db.py` for the outbox) and keep `db.py`
  DB-only. The third source (gateway's `compromised_nodes`) is merged at
  the one real call site instead — see `app.py` below.
- **`game/budget.py`**: wired the swap point that was deliberately
  stubbed in the 2026-10-01 scoring-rework session. `get_team_budget()`
  now tries `gateway_client.get_team_state(team_code)` first and uses its
  `balance` field if present; falls back to the existing
  `BUDGET_DEFAULT` env var on `None` (gateway unreachable/not
  configured) — exactly the one-line-swap-point design from that
  session's docstring, now actually wired.
- **`game/app.py` — `/api/submit_route`**:
  - Calls `gateway_client.get_team_state(team_code)` once per submission
    and unions its `compromised_nodes` (cast to `str`, since the spec's
    own example shows ints (`[12, 31]`) while our node IDs are strings
    like `"N15"` — treated as opaque and string-compared either way) into
    the existing `db.effective_compromised()` result. This call already
    carries its own 3s timeout and returns `None` on failure (same
    function `get_team_budget` uses), so this never adds submission
    latency beyond that single bounded call, and never blocks a
    submission on a down gateway.
  - **Route code feature** (spec §4 p2g4, new `game/route_code.py`):
    on a new-best accepted submission, computes
    `sha256(f"{team_code}:{'-'.join(route)}:{risk}")[:8]`, formatted as
    `XXXX-XXXX`, stores it on that submission row, returns it in the
    response as `route_code`, and sends it to the gateway via
    `send_event("output_issued", team_code, meta={"value": route_code})`
    — exactly per spec's `meta.value` field name.
  - **`solved` on every accepted submission** (not just new-best), per
    spec §4 p2g4 "On each accepted route: send solved", with
    `risk=risk_total`. **Points formula is a placeholder**
    (`max(0, 1000 - risk*10)`) — **flagging as still open with the
    gateway owner**, the spec only says "points formula, max points" is
    something we owe them in the questionnaire reply (§7.2), it doesn't
    give us a number. Don't treat this formula as final.
  - `wrong_attempt` is a capability behind `SEND_WRONG_ATTEMPTS` (default
    off) that currently does nothing when a submission is rejected — see
    "What's still open" below for why.
  - `/api/team/<code>/history` now also returns `route_code` per row
    (`null` unless that row was a new-best at submit time) — the
    frontend finds "the team's current best code" as the lowest-risk
    valid row with a non-null code, rather than needing a separate
    endpoint.
  - Drain thread started at app startup (`gateway_client.start_drain_thread()`
    in the `__main__` block), guarded against Flask's debug-mode reloader
    double-spawning it (checks `WERKZEUG_RUN_MAIN` so only the actual
    worker process starts it, not the reloader's parent).
- **`game/templates/team.html`**: new "Your Route Code" panel, amber-
  bordered, large monospace (`2.2rem`) code display with `user-select:
  all` (click once to select the whole code for copying) — sits right
  below the header, above the graph, so it's the first thing visible
  once a team has a best valid route. Populated two ways: immediately on
  a new-best submission response (`renderResult` -> `showRouteCode`), and
  on every page load/reload from `/api/team/<code>/history` (finds the
  lowest-risk valid row with a `route_code`) — so a team that closes and
  reopens the tab still sees their code, not just right after submitting.
  Hidden (`display:none`) until a team has one.
- **`brain/GATEWAY-INTEGRATION-SPEC.md`**: the full questionnaire/spec
  doc, saved verbatim as instructed.
- **`brain/API-CONTRACT.md`**: added a superseded notice at the top
  (the old `/api/integration/*` contract is being replaced by the
  gateway) and a new "Our outbound gateway behavior" section at the
  bottom, informational for the gateway owner (what events we send, our
  retry/timeout behavior, the open points-formula question).
- **Tested against a local mock gateway** (`game/gateway_mock.py`, new —
  implements `POST /api/events` and `GET /api/teams/{id}/state` per
  spec §3A/§3B, plus `/mock/events` + `/mock/set_state` + `/mock/reset`
  test-only helpers; explicitly NOT part of the real game, run
  standalone on :5099):
  - Real server on :5050 pointed at the mock (`GATEWAY_BASE_URL=
    http://127.0.0.1:5099`, `GATEWAY_API_KEY=mock-gateway-key`,
    `GATEWAY_DRAIN_INTERVAL=5`), mock seeded with `balance: 25.0`.
  - Submitted a route costing 22 (affordable under the mock's 25 balance
    but would exceed a smaller fallback) -> accepted, response showed
    `"budget": 25.0` — **confirms the gateway's live balance is actually
    used**, not the `BUDGET_DEFAULT=99` env fallback that was also set in
    the same test run. `route_code` returned (`"AA33-FB43"`) since it was
    the team's first/new-best submission.
  - `GET /mock/events` showed exactly two events landed with the correct
    shape: `solved` (`points: 920` = `1000 - 8*10`, `risk: 8`,
    `team_id: "TEAM1"` — our own team_code, unmapped) and `output_issued`
    (`meta.value: "AA33-FB43"`).
  - Set the mock's `compromised_nodes` to `["N15"]` via `/mock/set_state`,
    resubmitted the same previously-accepted route (passes through N15)
    -> rejected `"N15 is compromised"` — confirms the gateway's
    compromised-node list genuinely merges into submission validation,
    not just stored and ignored. Cleared it, resubmitted -> accepted
    again.
  - **Gateway-down test**: killed the mock mid-test, submitted a
    different route -> **still accepted** (11ms, no blocking on the
    unreachable gateway — connection was refused immediately, didn't
    need to wait out the 3s timeout in this case), `"budget": 99.0`
    confirms correct fallback to `BUDGET_DEFAULT` once `get_team_state`
    returned `None`. Queried the `gateway_outbox` table directly —
    confirmed the `solved` event was genuinely queued (`attempts: 2`,
    since both the inline send attempt and one drain-thread retry had
    already run and failed). Restarted the mock, waited one drain
    interval (~7s) -> `GET /mock/events` showed the queued event had
    landed with its *original* `event_id`, outbox confirmed empty (0
    pending) — full down/queue/recover/drain cycle verified end-to-end,
    not just read from the code.
  - Route-code determinism (direct unit-level check, not via the
    server): same team/route/risk called twice -> identical code both
    times; different team, different route, and different risk each
    independently produced a different code; format confirmed
    `XXXX-XXXX` (9 chars, dash at index 4).
  - **No-gateway-configured test**: started the real server with
    `GATEWAY_BASE_URL`/`GATEWAY_API_KEY` both unset — submission still
    worked, `"budget": 100.0"` (the plain `BUDGET_DEFAULT` fallback,
    identical to pre-integration behavior) — confirms local dev without
    any gateway setup is unaffected.
  - **Real browser verification** (agent-browser, same workflow as the
    2026-10-01 verification sessions): opened `/team`, logged in as
    TEAM1 (who already had a best valid route from the API tests above),
    confirmed the Route Code panel **renders on page load** (not just
    right after a fresh submission) showing the exact same code
    (`AA33-FB43`) the API test produced — screenshot
    `09-team-route-code-on-load.png` in
    `brain/verification-screenshots/`. Amber-bordered panel, large
    readable monospace code, correct placement above the graph, no
    layout issues.
  - Re-ran `solver.py`'s self-check after all changes — still passes,
    confirms this session didn't touch the validation/scoring core.
  - Cleaned up: closed the browser, killed both the mock gateway and the
    real test server, deleted the test `game.db`.
- **What's still open with the gateway owner** (flagging explicitly, per
  the instruction):
  - **Points formula**: `max(0, 1000 - risk*10)` is a placeholder I
    invented to have *something* non-zero and risk-sensitive to send —
    the spec asks us to reply with "points formula, max points" (§7.2),
    it doesn't hand us one. Needs a real answer before the event; the
    `solved` events we're sending right now carry made-up numbers.
  - **`wrong_attempt`**: NOT implemented/sent yet, on purpose. The spec
    is explicit for p2g1 ("each wrong key: send wrong_attempt") and p2g3
    ("each wrong token/endpoint submission: send wrong_attempt") but says
    nothing about it for p2g4 specifically in §4's entry for us — and a
    "wrong attempt" at a route-planning game (closed edge? wrong
    node? budget exceeded? these are pretty different from "wrong
    password") doesn't obviously map the same way. Built the capability
    behind `SEND_WRONG_ATTEMPTS` (default `false`, one-line flip once
    confirmed) rather than guessing and shipping it live.
  - Everything else from spec §7's questionnaire (stack/hosting,
    multiple-submissions-which-counts [already answered: best valid =
    lowest risk, matches what we built], anything we need to read
    [confirmed: balance + compromised_nodes, both wired]) is already
    covered by what's built — no other open questions from our side.
- What's broken / left for next session:
  - Nothing known-broken from what was tested against the mock.
  - **Not tested against the real gateway** — can't be, the real base
    URL/API key/test team T00 aren't shared yet (spec §6). Do this as
    soon as those are available: point `GATEWAY_BASE_URL`/
    `GATEWAY_API_KEY` at the real values and re-run (at minimum) the
    submission + outbox-retry tests above against the real thing, since
    a mock can only prove our side of the contract, not the real
    gateway's actual behavior.
  - `GATEWAY_BASE_URL`/`GATEWAY_API_KEY` currently empty by default
    (no-op mode) — same "must be set deliberately before the event"
    caveat as `ADMIN_TOKEN`/`BUDGET_DEFAULT`/`INTEGRATION_KEYS`.
  - The old `/api/integration/*` endpoints are still live and untouched
    — worth a decision later on when it's actually safe to remove them
    (once confirmed no other game still depends on them).
  - Admin panel (`admin.html`) has no visibility into the outbox queue
    depth or gateway connectivity — would be useful for organizers to
    see "N events queued, gateway last reachable at X" during the event,
    not built this session (not asked for).

## 2026-10-01 (Claude Code — fix: history table route-column overflow)
- **Fixed the one real bug flagged by the agent-browser verification
  session above**: `game/templates/team.html`'s submission-history table
  clipped long routes in the ROUTE column and overlapped the RISK column
  (confirmed visually in `06-team-route-rejected-budget.png` and
  `07-team-route-accepted.png`, 7-hop route rendered as
  `N00 → N03 → ... → N!`).
- **Root cause**: the table used default `table-layout: auto` with only
  `max-width`/`overflow-x: auto`/`white-space: nowrap` on the `.route-cell`
  — under auto layout, a `max-width` on a `td` doesn't actually constrain
  column width (columns size to content first), so the cell was free to
  grow past its visual column and overlap the next one; the intended
  `overflow-x` scrollbar never had a fixed box to scroll within.
- **Fix** (`game/templates/team.html`): switched `#history-table` to
  `table-layout: fixed` with explicit pixel widths on the #/Status/Risk/
  Event-T columns (28px/90px/55px/70px), leaving the Route column to take
  the remaining space automatically. Changed `.route-cell` from
  `white-space: nowrap` + horizontal scroll to `white-space: normal` +
  `word-break: break-word` — **routes now wrap onto multiple lines within
  their own cell** rather than scrolling or truncating. Chose wrap over a
  hover/click-to-expand: a team's own just-submitted route is exactly what
  they want to glance-check in a noisy event hall, and hiding it behind an
  interaction is worse UX than letting the cell grow taller.
- **Verified against the real rendered page**, not just the CSS source —
  re-ran the same agent-browser workflow from the verification session:
  fresh server, `/team`, logged in as TEAM1, submitted the **exact same
  7-hop route that exposed the original bug**
  (`N00,N03,N04,N05,N06,N07,N59`) plus the known-good accepted route, to
  reproduce the original two-row screenshot layout.
  - `08-team-history-route-wrap-fixed.png` — the 7-hop rejected route now
    wraps cleanly onto two lines inside the ROUTE cell, RISK column still
    shows `—` with no overlap, table stays aligned at normal width.
  - Stress-tested further with an 8-hop route
    (`N00,N01,N02,N03,N04,N05,N06,N07,N59`, found via the same
    brute-force + `validate_path` search approach as the original bug
    repro) — wraps correctly across two lines, three-row table still
    intact, no regression (screenshot taken to `/tmp`, not kept —
    transient check, the 7-hop case above is the one that matters since
    it's the documented repro).
  - Checked at mobile width (390×844 via `agent-browser set viewport`)
    per the project's responsive requirement — route wraps one node per
    line at that width, stays fully inside its column, no horizontal
    scroll, no breakage.
  - `agent-browser console` after all of the above: zero errors/warnings.
  - Cleaned up: closed the browser, killed the test server, deleted the
    test `game.db`.
- What's broken / left for next session: nothing known-broken. This
  closes out the one open item from the prior verification session.

## 2026-10-01 (Claude Code — real browser verification via agent-browser)
- **This finally closes the open item flagged in every frontend session
  since 2026-09-28**: "Claude-in-Chrome not connected, no real
  click-through happened." Installed and used `agent-browser`
  (https://github.com/vercel-labs/agent-browser, Rust CLI, drives a real
  headless Chrome for Testing instance) instead — `npm install -g
  agent-browser && agent-browser install` (downloaded Chrome 154.0.8037.92
  for mac-arm64, ~182MB, one-time). This is a genuinely different/working
  path from the Claude-in-Chrome extension dependency that was blocked all
  prior sessions.
- **Setup**: fresh `game.db`, real server (`ADMIN_TOKEN=test-token
  BUDGET_DEFAULT=25 INTEGRATION_KEYS=game3:g3key`, port 5050, via the
  project's `.venv`). Chose `BUDGET_DEFAULT=25` deliberately so both an
  acceptable route (cost=22) and a clean over-budget rejection (found a
  real, open-at-t=0 route costing 33 via brute-force DFS + `validate_path`
  filtering, not guessed) were reachable in the same session.
- **Workflow used**: `open` -> `snapshot` (accessibility tree with `@eN`
  refs) -> `fill`/`click` by ref -> `screenshot`. All 8 screenshots saved
  to new `brain/verification-screenshots/`.
- **Real bug in my own test process, not the app**: the node-compromise
  grid re-renders its DOM on every toggle click, which invalidates every
  `@eN` ref from a prior snapshot — clicking a stale ref after a re-render
  silently hits whatever element now occupies that ref number. First
  attempt at toggling N15 compromised this way actually toggled N03, then
  N13, before landing on N15 correctly. **Lesson for next time**: take a
  fresh `snapshot` immediately before every single click on a
  dynamically-re-rendering list, don't batch clicks against one cached
  snapshot. Verified the final compromised-state via `GET /api/graph`
  (`compromised_nodes: ["N15"]`) before trusting the screenshot, so the
  actual result captured is correct — this was a process hiccup during
  the session, not a reported bug in the app itself.
- **What was verified and what the screenshots actually show**:
  1. `01-admin-login.png` — `/admin` on load: dark panel, token input,
     "Enter" button. Clean, legible, no layout issues.
  2. `02-admin-logged-in.png` — after filling the real token and clicking
     Enter: full panel renders (event clock, global compromise grid,
     per-team compromise controls). Good contrast throughout.
  3. `03-admin-clock-set-60.png` — filled `60` into the minute field,
     clicked "Set clock to this minute": **the on-screen `t = X.XX min`
     readout actually changed from `0.00` to `60.00` live, no reload** —
     confirms the UI genuinely reflects server state, not just that the
     API call succeeded underneath.
  4. `04-admin-node-compromised.png` — N15 clicked compromised (after
     correcting the stale-ref mistake above): **N15 renders with a
     distinct red highlight** against the other (unstyled) node chips,
     clearly visible, matches `compromised_nodes` from the live API.
  5. `05-team-graph-view.png` / `05b-...-downloads-and-form.png` —
     `/team`, logged in as TEAM1: vis-network graph actually renders (not
     just the fallback text notice) — 60 nodes, edges, hideout (green,
     N00) and extraction (red, N59) correctly colored per the legend,
     closed-now edges visibly faded vs. open ones. Download links
     (`⇩ graph.json`, `⇩ graph.csv`) and the submission form both render
     correctly below the graph. Money Heist theme (near-black bg, red/
     amber accents, Oswald/IBM Plex Mono fonts per the 2026-09-30 entry)
     renders as designed — legible, no contrast problems at this
     resolution.
  6. `06-team-route-rejected-budget.png` — submitted the real over-budget
     route (`N00,N03,N04,N05,N06,N07,N59`, cost=33 > budget=25): red-
     bordered panel, headline "BLOWN — ROUTE REJECTED", and the literal
     reason string `total cost 33 exceeds budget 25.0` rendered verbatim
     underneath — confirms the new budget-cap rejection path (added this
     session, see the entry above) actually reaches the browser correctly
     end-to-end, not just via curl.
  7. `07-team-route-accepted.png` — submitted the known-good route
     (`N00,N15,N30,N45,N59`, risk=8, fits budget=25): green-bordered
     panel, "JOB'S DONE — ROUTE ACCEPTED", three stat tiles **TIME 35 /
     RISK (SCORE) 8 / COST 22** (confirms the risk-only scoring rework
     from this session renders with the right label and right number,
     not leftover `score` text), "New personal best" badge, and the
     history table below updated with both the accepted and earlier
     rejected rows.
- **Real visual bug found** (not a process mistake, an actual rendering
  issue in `team.html`): **the submission-history table's ROUTE column
  clips long route strings** — the 7-node rejected route renders as
  `N00 → N03 → N04 → N05 → N06 → N07 → N!` with the tail cut off and
  overlapping into the RISK column (visible in both `06-...` and
  `07-...` screenshots, same row). Short routes (the 5-node accepted one)
  render fine. The column has no wrap/truncate-with-ellipsis handling for
  long content — worth a fix (e.g. `white-space: normal` + word-wrap, or
  truncate with `…` and a tooltip) before the event, since event routes
  could easily run longer than 7 hops. **Not fixed this session** — this
  task was verification-only, flagging for a follow-up.
- **Console check**: `agent-browser console` on both `/admin` and `/team`
  after full interaction (login, clock set, node toggle, two route
  submissions, graph render) — **zero console output on either page**, no
  errors/warnings/logs. Clean.
- **Not covered this session** (out of scope for the 8-step verification
  asked for, flagging so it's not assumed done): mobile/narrow-width
  rendering, the admin panel's per-team compromise UI interaction (only
  the global grid was exercised), the leaderboard/submissions-log/export
  sections of the admin panel, and the team page's history-table
  ACCEPTED/REJECTED pill styling wasn't zoomed in on for contrast beyond
  what's visible in the full-page screenshots above.
- Cleaned up: closed the agent-browser session, killed the test server,
  deleted the test `game.db`.
- What's broken / left for next session:
  - ~~Fix the history-table route-column text overflow in `team.html`~~ —
    **fixed and re-verified in the very next session, see the entry
    above this one** (dated the same day, appears above in the log since
    newest entries sort to the top).
  - Still not covered: admin per-team-compromise UI click-through,
    leaderboard/export sections visually (mobile-width was spot-checked
    in the fix-verification session above, at least for the team page).
    Recommend extending this same agent-browser approach rather than
    reverting to manual browser testing, now that it's proven to work in
    this environment.

## 2026-10-01 (Claude Code — scoring model rework: risk-only + hard caps)
- **Scope addition, confirmed by Rudra**: the weighted-sum score
  (time*1.0 + risk*4.0 + cost*0.5) is replaced. New model: minimize RISK
  only, subject to two hard constraints — total time <= the event's
  deadline AND total cost <= the submitting team's budget. A route that
  breaks either cap is REJECTED outright (same as a closed edge or
  compromised node), not penalized in a score. All milestones 1-4 were
  already done/tested before this session; this is a core-model change on
  top of that, not a new milestone.
- **Why plain Dijkstra can't do this**: minimizing a single weighted sum
  (the old model) can silently let a cheap detour's risk/time "buy down"
  an otherwise-bad cost, and minimizing risk alone ignores the caps
  entirely. A route that's worse on risk might be the *only* one that
  fits the budget — need the actual min-risk route among only the
  feasible-under-both-caps routes.
- **`game/solver.py`**:
  - `validate_path()` (still the single source of truth app.py imports)
    gained optional `deadline=`/`budget=` kwargs. When given, it now also
    checks `total_time <= deadline` and `total_cost <= budget` after
    confirming the route is real/open/uncompromised, returning the exact
    reason string (`"total cost 22 exceeds budget 10.0"` /
    `"total time 35 exceeds deadline 20"`) consistent with its existing
    reason-string style.
  - New `min_risk_constrained(graph, start, goal, *, t, compromised,
    deadline, budget)` — the actual constrained solver. State-augmented
    best-first search over `(node, cumulative_cost)`, tracking
    Pareto-minimal `(risk, time)` pairs per state (neither dominates the
    other, so both are kept unless one state beats another on both axes).
    No bucketing/discretization needed: edge time/cost are small
    non-negative integers in this graph (time 1-15, cost 1-20 per edge,
    176 edges) and budget/deadline are themselves finite integers, so
    cumulative cost has at most `budget+1` exact integer values to track —
    exact DP, not an approximation. Over-budget/over-deadline partial
    paths are pruned immediately, not explored.
  - Self-check (`run_selfcheck`) extended to prove, on top of the existing
    shortest-time-vs-best-score trap: (a) the graph is solvable under a
    generous deadline/budget combo, and the constrained solver's own route
    round-trips through `validate_path()`; (b) scans budgets between the
    fastest-by-time route's cost and the (old) best-by-score route's cost
    to find one where `min_risk_constrained` returns a route that's
    genuinely different from the fastest-by-time route AND has strictly
    lower risk — proving the constrained model surfaces something plain
    Dijkstra-by-time structurally cannot. Scanning a budget range rather
    than a fixed offset, because a hardcoded offset (tried `+6` first)
    turned out to be specific to seed 42's graph and failed on other
    seeds (1, 3, 99) — re-verified passing on seeds 1/2/3/42/99/1000 after
    the fix.
  - Found and fixed a transient issue while building this: at `t=0` the
    low-risk alternate route uses an edge (`N15->N58`, window 59-112)
    that isn't open yet — this is correct behavior (the solver respects
    live windows), not a bug; the self-check now uses `t=None` for the
    constrained-model proof specifically because it's testing the
    solver's constraint logic in isolation, not replaying the live clock.
- **`game/budget.py` (new)**: `get_team_budget(team_code)` — currently
  returns one shared default from `BUDGET_DEFAULT` env var (default 100).
  Written so the planned swap to a real call to the central cross-game
  dashboard (still being built elsewhere, same pattern as the
  `INTEGRATION_KEYS` gateway possibility noted in the 2026-09-29 entry) is
  a one-line change inside this one function — nothing else in the
  codebase (solver.py, app.py, or any future caller) needs to change when
  that swap happens.
- **Deadline**: stayed as `graph.json["event_duration"]` (already existed,
  120 minutes) rather than adding a new field — it was already exactly
  "total time cap for the whole event," so reused as-is.
- **`game/app.py`**:
  - `/api/submit_route`: now calls `validate_path(..., deadline=
    GRAPH["event_duration"], budget=get_team_budget(team_code))`. Score
    stored/returned is now `risk_total` directly (lower = better, same
    direction as before). Response echoes `deadline`/`budget` alongside
    the existing fields so a team can see what they were actually
    measured against, not just the rejection reason text.
  - **Breaking change** (as instructed) to response shapes:
    `/api/leaderboard`, `/api/integration/leaderboard`, and
    `/api/integration/result/<team_code>` no longer return a combined
    `score`/`best_score` field — they return `risk`/`time`/`cost`/
    `budget`/`deadline`/`has_valid_route` instead, via a new shared
    `_team_summary()` helper (leaderboard and integration-leaderboard were
    duplicating the same per-team lookup, now both call it). Documented
    in brain/API-CONTRACT.md's responsibility — **the other four games'
    developers integrating against `/api/integration/*` need to update
    their field reads** (`best_score` -> `risk`); flagging here since
    that contract doc exists specifically for them.
  - `admin_export`/`admin_export.csv` and `/api/admin/submissions` were
    NOT changed — they read the DB row's `score` column directly, which
    now holds the risk value under the hood, so they keep working without
    code changes, just a now-slightly-stale field *name* (not worth
    touching, out of scope for this session).
  - Removed the now-meaningless `weights` field from `/api/graph`'s
    response (there's no weighted sum anymore) and the unused `WEIGHTS`
    module global.
- **Frontend fixes** (not explicitly in scope, but the breaking response
  changes above would have silently broken these on load — fixed as the
  root-cause follow-through, not deferred):
  - `admin.html`'s leaderboard renderer read `row.best_score` (now
    `undefined.toFixed` crash) — fixed to read `row.risk`, header relabeled
    "Best (lowest) risk".
  - `team.html`'s result panel rendered a `b.score` stat tile from
    `/api/submit_route`'s breakdown, which no longer has that key — removed
    the tile (risk is already shown and IS the score now). History table's
    "Score" column header relabeled "Risk" (the underlying field, `r.score`
    from `/api/team/<code>/history`, is unchanged — that endpoint reads the
    DB column directly, still populated).
- **Tested against the real server** (fresh `game.db`, port 5050):
  - `ADMIN_TOKEN=test-token BUDGET_DEFAULT=100`: submitted the cheap/risky
    route (cost=8, risk=57) -> accepted, `is_new_best: true`. Submitted the
    low-risk route (cost=22, risk=8) -> accepted, `is_new_best: true`
    (risk 8 < 57 — confirms best-tracking now compares risk, not the old
    score).
  - `BUDGET_DEFAULT=10` (restart, fresh db): the cost=22 low-risk route ->
    rejected, `"total cost 22 exceeds budget 10.0"`. The cost=8 risky
    route -> still accepted. Confirms a route can be rejected purely for
    cost even though it's the better route on every other axis — the
    actual breaking-change behavior requested.
  - Deadline rejection verified directly via `validate_path(... ,
    deadline=20, budget=100)` on the cost=22/time=35 route -> rejected,
    `"total time 35 exceeds deadline 20"`.
  - `/api/leaderboard` (admin token), `/api/integration/leaderboard`, and
    `/api/integration/result/TEAM1` (dev game key) all confirmed returning
    `risk`/`time`/`cost`/`budget`/`deadline`/`has_valid_route`, no
    `score`/`best_score` anywhere.
  - Re-ran `solver.py`'s self-check standalone and across seeds
    1/2/3/42/99/1000 — all pass.
  - Cleaned up: killed the test server, deleted the test `game.db`.
- What's broken / left for next session:
  - Nothing known-broken from what was tested.
  - `brain/API-CONTRACT.md` was NOT updated this session to reflect the
    `/api/integration/*` field changes (`best_score` -> `risk` etc.) —
    **do this before telling the other four games' developers**, since
    that doc is their only reference and is now stale on this point.
  - No actual browser click-through of the frontend fixes above (same
    long-standing Claude-in-Chrome-not-connected caveat as every prior
    frontend session) — the JS was read/patched against the real response
    shapes, not click-tested in a live browser.
  - `BUDGET_DEFAULT` env var currently defaults to 100 if unset — same
    "must be set deliberately before the event" caveat as `ADMIN_TOKEN`/
    `INTEGRATION_KEYS`: confirm the real default (or per-team values, once
    the dashboard swap lands) before the live event, don't ship an
    arbitrary placeholder number live.

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
