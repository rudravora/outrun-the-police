# Context — CODEVERSE 2.0 & "Outrun the Police"

This file is background/world context for anyone (human or AI) picking up
this build. It's the "why does this game exist and what does it fit into"
document. For the buildable spec, see `PRD.md`. For active status, see
`logs.md`.

## What CODEVERSE 2.0 is

A heist-themed, two-phase hacking/puzzle event run by codeAI (Rudra's college
club, DJSCE Mumbai).

**Phase 1 — The Royal Mint** (5 independent challenges): vault cryptography,
Python debugging, web/JS investigation, data & routing analysis, ML
prediction. Each is standalone and scored independently.

**Phase 2 — The Escape** (5 interlinked challenges): teams who "robbed the
mint" now try to escape. Each of the first four Phase 2 games produces one
"key," and Game 5 combines all four keys into a final extraction sequence.

| # | Game | Category | Owner(s) | Produces |
|---|------|----------|----------|----------|
| 1 | Erase the Money Trail | SQL/Pandas/forensics | Bhargav, Vedika | Deletion Key |
| 2 | Black Market | Risk/reward economy meta-game | Balganesh | (money multiplier, not a hard key) |
| 3 | Find the Control Server | APIs/web forensics | Ashok, Siddharth | Control-Server Token |
| 4 | **Outrun the Police** | **Graph algorithms/optimization** | **Rudra, Omkar** | **Escape Route + Risk Value** |
| 5 | Final Extraction | Systems integration | Rutuja, Unnatee | Final score |

Game 2 (Black Market) is an optional side-economy: teams can spend heist
money for advantages, at increasing personal cost. It doesn't gate Game 5
directly but affects a team's final score and possibly their resources
going into other games.

Game 5 needs: **Deletion Key (G1) + Shutdown Code + Control Token (G3) +
Escape Route (G4)** to unlock the final extraction interface. Wrong
submissions there trigger penalties; final score weighs money retained, time
remaining, risk accumulated, incorrect attempts, and hints used. Top 3 teams
by successful extraction score win the event.

## Where Game 4 fits thematically

The narrative: teams have already broken into the Mint (Phase 1) and are now
fleeing across the city before the police lock it down. "Outrun the Police"
*is* that chase, converted into a hard optimization problem instead of a
timed physical/visual chase — appropriate for a code-focused audience.

Thematic tie-ins worth keeping in the copy/UI:
- Nodes = city locations (safehouses, alleys, checkpoints, garages, bridges).
- Edges = roads/routes between them.
- "Compromised" location = police have identified it (optionally: triggered
  by a bad result in another Phase 2 game, e.g. Game 3's control-server
  trace exposing a team's position).
- Availability windows = patrol shift changes, road closures, curfews.
- The team's `risk` total = how "hot" their escape was, feeding into Game 5's
  final risk-accumulated scoring.

## Game mechanics in plain English

Teams get a city map: 50+ locations, 100+ roads. Every road costs `time`,
`risk`, and `cost` to use, and is only open during a specific window of the
event. Teams must compute — not guess — a path from their hideout to the
extraction point. The twist: the fastest path is deliberately not the best
one, because risk and cost matter too, and some roads close or some
locations get flagged "compromised" *while the event is running*. Teams
submit their route to a website; the website checks it's legal *right now*
and gives them a score. Best submission wins them their piece of the Game 5
puzzle.

## Live event example (agreed narrative walkthrough)

This is the illustrative example already validated with Rudra — use it as
the acceptance-test story when building:

1. **T+0:00** — Event starts, clock at 0. All roads open, nothing
   compromised. A team logs in, downloads the graph, starts computing a
   route with their own script (Dijkstra/A*-style, weighing time+risk+cost).
2. **T+0:12** — They submit route A. Backend checks it's a real path, all
   edges open at t=12, no compromised nodes involved → accepted, scored,
   saved as their current best.
3. **T+0:25** — Organizer marks a node (say `N22`) compromised via the admin
   panel — thematically because that team (or another) got a bad result in
   Game 3. Any route through `N22` is now invalid for *new* submissions.
   Separately, an edge with a 0–30 min window is about to close.
4. **T+0:31** — Team resubmits their same route A (which used `N22`) →
   rejected, with a clear reason ("N22 is compromised"). They must replan
   live.
5. **T+0:40** — Team submits route B, avoiding `N22`, using an edge that's
   still open. Accepted — but it trades off worse time for better risk than
   route A. This is the "optimize multiple conditions" moment made visible.
6. **T+0:55** — Submission window closes. Each team's best *valid* submission
   is locked in.
7. **Handoff** — The locked-in route's risk value, plus the team's outputs
   from Games 1 and 3, becomes part of what they punch into Game 5's Final
   Extraction interface. No valid route ⇒ they can't complete extraction.

Meanwhile organizers watch a live admin view of who has a valid route, their
score, and how many rejected attempts they've burned (rejected attempts may
cost points per the overall event rules).

## Design principles carried over from how Rudra likes to build

(See also `/projects/.../principles-and-ways-of-working.md` in memory —
summarized here for a build agent that won't have that file.)

- Ship a working, testable thing fast; don't over-engineer before the core
  loop is proven.
- Prefer free/open tooling first.
- Python backend preferred but not a hard constraint — pick whatever ships
  fastest and is reliable on the day.
- This is a **live, timed, high-stakes event tool** — correctness of
  validation logic and uptime during the event matter more than polish.
