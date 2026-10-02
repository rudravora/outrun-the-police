# Task Split — Outrun the Police

Purpose of this file: so you and your teammate build **different things in
parallel** instead of duplicating work or stepping on the same files.
Rudra (+ Claude Code) owns the core game engine in sequence
(graph → backend → admin → team frontend, per `PRD.md` §12, Milestones
1–4). Your teammate takes everything below, which is real, needed work but
mostly touches **separate files**, so it can happen at the same time
without merge conflicts.

## Workflow

- Teammate creates his own branch off `main` (e.g. `git checkout -b
  teammate/deploy-and-ops`) and pushes there — don't work directly on
  `main`.
- He should still **read `brain/context.md`, `brain/PRD.md`, and
  `brain/logs.md`** first (see `ONBOARDING.md`), so his work matches the
  actual data model and API shape Rudra's side has already built — nothing
  below should require changing `game/app.py`, `game/db.py`, `game/solver.py`,
  or the templates Rudra's side owns. If he finds he *needs* to touch one
  of those, that's a sign to sync up first, not just push a change.
- He appends his own entries to `brain/logs.md` same as any other session
  — that's still the single shared log, even across branches. Merge that
  file carefully (it's append-only in practice, so conflicts should just be
  "both additions kept").
- When his branch is ready, open a PR against `main` rather than merging
  directly, so Rudra can review before it lands — especially anything that
  touches deployment/production config.

## What he owns: Milestones 5 & 6 from PRD.md §12, plus supporting ops work

### 1. Formal automated test suite (supports Milestone 5)
Everything so far has been tested manually (curl commands, manual restarts,
manual browser checks). Turn that into a real, repeatable `pytest` suite
under a new `tests/` folder, covering — at minimum — everything already
verified manually per `brain/logs.md`:
- A structurally valid route within all windows and avoiding compromised
  nodes → accepted, and its score matches `game/solver.py`'s reference
  score exactly.
- Each rejection reason fires correctly: nonexistent path, edge used
  outside its availability window, route through a compromised node.
- Grandfathering: a route accepted before a node is marked compromised
  stays accepted; only new submissions are checked against new state.
- Event clock gating: an edge open at t=10 but closed at t=40 behaves
  correctly at both times.
- Best-score tracking per team, and leaderboard ordering across multiple
  teams.
- Admin auth: endpoints reject missing/invalid tokens.
- Persistence: state survives a server restart (this one's awkward to
  automate — a subprocess-based test that starts the server, hits it,
  kills it, restarts it, and re-checks state is worth the effort given how
  important this property is for a live event).

This should import `game/solver.py`, `game/db.py`, and hit `game/app.py`'s
routes — read-only usage of those modules, not edits to them.

### 2. Load / concurrency test (Milestone 5)
A simple script (locust, or even a plain `asyncio`/`concurrent.futures`
script hitting the API) simulating 15–30 teams submitting routes
concurrently, to catch any SQLite locking or race-condition issues before
event day. Report findings in `brain/logs.md` — if SQLite chokes under
concurrent writes, that's an important enough finding to flag to Rudra
before Milestone 6, not something to quietly work around.

### 3. Deployment (Milestone 6)
Get this actually **hosted**, not just runnable on a laptop:
- A `requirements.txt` (pin versions).
- A `Procfile` / `render.yaml` / equivalent for whichever free host you two
  pick (Render or Railway are the two mentioned in the PRD).
- Document the environment variables needed (admin token, any config) —
  in a new `DEPLOYMENT.md`, not hardcoded.
- A tested fallback path: instructions for running it as a laptop-on-venue-
  LAN server instead, in case hosting has issues on the day (also in
  `DEPLOYMENT.md`).
- Actually deploy it to a real URL and confirm the live admin panel + a
  test submission work end-to-end against the hosted instance, not just
  locally.

### 4. Team code generation + event-day ops
- A script to generate the actual team codes for registered teams (however
  many sign up), output as a CSV organizers can hand out.
- A short `RUNBOOK.md` for whoever is sitting at the admin panel during the
  live event: how to log in, when to push clock updates (tie this to the
  event's actual schedule once you have it), how to handle a team claiming
  a bug (what to check before assuming it's real), and how to export final
  results at the end for handoff to the Game 5 team.

## What NOT to duplicate

- Don't rebuild or restyle the team-facing frontend — that's Milestone 4,
  Rudra's side.
- Don't change the scoring formula or graph generation — those are locked
  in from Milestone 1 and verified; if you think they need to change, flag
  it in `logs.md` and talk to Rudra, don't just change `graph_gen.py` on
  your branch (regenerating the graph invalidates the "verified solvable
  with a real trap scenario" work already done).
- Don't add a second admin panel or a second auth system — extend the
  existing one if something's missing, don't build a parallel one.
