# PRD — "Outrun the Police" (CODEVERSE 2.0, Phase 2 · Game 4)

## 1. Background

CODEVERSE 2.0 is codeAI's flagship college event, run as a two-phase heist-themed
hacking/puzzle competition:

- **Phase 1 — The Royal Mint**: 5 independent challenges (crypto, debugging, web
  investigation, data/algorithms, ML).
- **Phase 2 — The Escape**: 5 interlinked challenges. Teams must clear (or attempt)
  all of them to gather four keys, which combine in **Game 5 — Final Extraction**.

This PRD covers **Phase 2, Game 4: "Outrun the Police"**, owned by Rudra (and
Omkar). Category: **Graph Algorithms / Optimization**.

## 2. One-line pitch

Teams are handed a live, changing city map and must compute — not guess — an
escape route from their hideout to the extraction point that survives closing
roads, compromised locations, and competing costs (time / risk / cash), then
submit it to a web app that validates and scores it in real time.

## 3. Official brief (verbatim requirements from event doc)

- **What participants get:** a network of 50+ locations and 100+ connections.
  Each connection has: `time`, `risk`, `cost`, `availability window`.
- **What they do:** calculate a route to the extraction point satisfying all
  constraints.
- **How to make it tough:**
  - Shortest route is *not* necessarily safest.
  - Some routes close after specific times.
  - Previous challenges can mark locations as compromised.
  - Teams must optimize multiple conditions simultaneously.
- **Implementation:** JSON/CSV graph + hidden test cases. Participants
  write/adapt an algorithm to calculate the route.
- **Output:** Valid escape route + risk value → feeds into Game 5 (Final
  Extraction), which needs Deletion Key (G1) + Shutdown Code (G2, if applicable)
  + Control Token (G3) + Escape Route (G4).

Full context on the other games and how this fits the event narrative lives in
`context.md` in this folder.

## 4. Goals

1. Ship a **web-hosted** game (not a local script hand-in) with a Python
   backend, usable during the live event on venue WiFi or a public host.
2. Make "shortest ≠ best" actually true by construction — a naive shortest-path
   submission must score worse than a route that balances risk/cost.
3. Support **live event drama**: organizers can mark locations compromised and
   the event clock advances in real time, changing which routes are legal,
   without redeploying anything.
4. Give every team instant, deterministic feedback (accept/reject + score
   breakdown) so there's no ambiguity or manual grading during the event.
5. Produce the exact artifact Game 5 needs: a validated escape route + a risk
   value, tied to a team ID.

## 5. Non-goals

- Not building a multiplayer real-time visual chase (no live avatars moving
  on the map).
- Not doing per-team unique graphs in v1 (one shared graph for all teams,
  unless later decided otherwise — see Open Questions).
- Not integrating directly with Games 1–3/5's codebases — integration is via a
  shared "team keys" table/API contract only.

## 6. Users

- **Competing teams** (~15–30 teams expected): use the team-facing web page.
- **Organizers/volunteers running Game 4**: use the admin panel during the
  event to trigger compromise events and control the event clock.
- **Game 5 owners (Rutuja, Unnatee)**: consume this game's output (escape
  route + risk value) as one of four required inputs.

## 7. Core game loop

1. Event starts → event clock starts at `t=0`.
2. Team logs in with a team code (assigned at registration).
3. Team fetches the current graph state (nodes, edges, which edges are
   currently open given `t`, which nodes are compromised).
4. Team computes a route offline (their own algorithm, any language) from
   `HIDEOUT` to `EXTRACTION`.
5. Team submits the route (ordered list of node IDs) via the web app.
6. Backend validates against the **live** graph state at submission time:
   - Path is a real sequence of existing edges.
   - No edge used outside its availability window (checked against current
     event time).
   - No node in the path is currently compromised.
7. Backend computes score = weighted combination of total time, total risk,
   total cost (weights published in the rules so teams can optimize for it).
8. Team sees instant result: accepted/rejected + score breakdown. Best valid
   submission per team is kept.
9. Organizers may, at any point, mark a node compromised or advance/adjust the
   event clock — this can invalidate a team's *previously accepted* route if
   they haven't locked it in yet (see Open Questions on lock-in timing).
10. At game close, each team's best valid submission's **risk value** is
    exported for Game 5.

## 8. Functional requirements

### 8.1 Graph data
- ≥50 nodes, ≥100 edges, generated once before the event, saved as JSON
  (source of truth) with a CSV export for teams who prefer that format.
- Exactly one `HIDEOUT` node and one `EXTRACTION` node, guaranteed reachable
  from each other under *some* valid time/compromise state (verified by a
  reference solver before the event).
- Each edge: `id, from, to, time, risk, cost, window_start, window_end`
  (directed or undirected — decide in Open Questions).
- Graph must be dense/tricky enough that pure shortest-path (by time or by
  hop count) is a suboptimal or invalid answer for at least one designed
  scenario.

### 8.2 Team-facing web app
- Team login via team code (no passwords needed — codes distributed at
  registration).
- View current graph: visually (graph rendering) and as downloadable
  JSON/CSV.
- Live indicators: current event time, list of currently compromised nodes,
  list of currently-closed edges.
- Route submission form (paste ordered node list / IDs).
- Instant result panel: valid/invalid, and if valid, time/risk/cost breakdown
  and combined score.
- Personal submission history (their own attempts only).
- Public or team-scoped leaderboard (decide visibility in Open Questions).

### 8.3 Admin panel
- Password/token-protected, separate route from the team app.
- Toggle any node's compromised state on/off, with immediate effect on
  subsequent validations.
- Control the event clock: start, pause, jump to a specific minute (for
  testing and for recovering from delays).
- View all team submissions (valid and rejected) live.
- Manual override / dispute resolution: mark a specific submission as
  accepted despite a validation failure (for edge cases / bugs found live).
- Trigger a "compromise" as a scripted event tied to a specific event-minute
  (e.g., "at minute 20, compromise N14, N22" pre-programmed) as well as ad hoc
  manual triggers.
- Export final results (team → best route, risk value, score) as CSV/JSON
  for Game 5 hand-off.

### 8.4 Backend / API
- Python backend (Flask preferred, per stated preference — not a hard
  requirement).
- Persistent storage (SQLite is enough at this scale) for: teams, graph
  state overrides (compromised nodes), event clock state, submissions,
  scores.
- All validation logic server-side — never trust client-computed scores.
- Idempotent, replayable: if the server restarts mid-event, state must
  survive (SQLite file, not in-memory only).
- Rate-limit or de-duplicate spammy submissions if needed (nice-to-have).

### 8.5 Scoring
- Formula: `score = w_time * total_time + w_risk * total_risk + w_cost * total_cost`
  (lower is better) or an inverse for a "higher is better" leaderboard —
  decide sign convention early and keep it consistent everywhere (backend,
  frontend, docs).
- Weights published in the rules before the event so "optimize multiple
  conditions" is a real, informed decision for teams.
- Invalid route = no score, always rejected with a clear reason string.

## 9. Non-functional requirements

- Must run reliably on venue WiFi with 15–30 teams hitting it concurrently —
  lightweight stack, no heavy dependencies.
- Must be host-able for free/cheap (Render/Railway/PythonAnywhere) or
  runnable on a laptop as a LAN server as a fallback — document both paths.
- Should degrade gracefully: if a team's browser can't render the graph
  visualization, the JSON/CSV download must still let them play.
- Admin actions must take effect within a few seconds, no redeploy needed.

## 10. Success criteria

- At least one designed "trap" scenario exists where the fastest route by
  time is clearly not the best-scoring route, and this is verified by a
  reference solver before the event.
- A live compromise event and a live clock-driven road closure can each be
  demonstrated to change the validity/score of an already-planned route,
  without any code deploy.
- Every team that submits a structurally valid route gets a score within
  ~1 second.
- Game 5 owners can pull, per team, a risk value keyed by team code with no
  manual lookup.

## 11. Open questions (resolve before/while building)

1. **Shared graph vs per-team graphs** — one graph is simpler and easier to
   balance/test; per-team graphs prevent copying answers between teams but
   multiply testing effort. Default: shared graph for v1.
2. **Directed vs undirected edges** — does a road work both ways? Default:
   directed, since "the police" and one-way heist logistics make directed
   edges more thematic and let us create asymmetric traps.
3. **Lock-in behavior** — if a team's accepted route becomes invalid later
   because of a new compromise event, do they keep their previously-earned
   score (grandfathered) or lose it and must resubmit? Default: grandfather
   the score of a route valid *at the time it was accepted*; only future
   submissions are checked against new state.
4. **Compromise triggers** — purely organizer-manual, or programmatically
   linked to another Phase 2 game's results (e.g., a bad Game 3 result
   compromises one of that team's nodes)? Default for v1: manual + a
   pre-scripted timeline; auto-linking to other games is a stretch goal
   only if time allows and the other games expose a usable signal/API.
5. **Leaderboard visibility** — public to all teams (adds competitive
   pressure) or admin-only (avoids copying strategies)? Default: admin-only
   live view; a delayed/partial public leaderboard is a nice-to-have.
6. **Team auth** — team codes only (simplest) vs code + password. Default:
   codes only, generated and distributed at registration.

## 12. Milestones (see `logs.md` for live status)

1. Graph generator + reference solver (proves solvability, finds the
   "trap" scenario).
2. Backend: data model, graph state endpoint, submission validation +
   scoring.
3. Admin panel: compromise toggles, clock control, live submissions view.
4. Team frontend: graph view, submission form, results, personal history.
5. End-to-end test with fake teams simulating the live-event example in
   `context.md`.
6. Deploy (hosted URL) + dry run with organizers.
7. Event day: monitoring + manual override readiness.
