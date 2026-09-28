# GEMINI.md — Outrun the Police (build agent instructions)

You are building **"Outrun the Police"**, Phase 2 Game 4 of codeAI's
CODEVERSE 2.0 event, for Rudra. This file is your standing instructions.
Read the other files in this `brain/` folder before writing any code:

1. `context.md` — what this game is, how it fits the larger event, the
   agreed live-event example. Read this first for the "why."
2. `PRD.md` — the actual spec: requirements, data model, API surface,
   scoring, milestones, and open questions with stated defaults.
3. `logs.md` — running build log, shared with any Claude Code sessions that
   also work on this project. **Read the most recent entries before
   starting work**, and **append a new entry every time you finish a
   milestone or make a nontrivial decision**, using the format already in
   the file. This is the single source of truth across tools/sessions —
   treat it as more reliable than any other context you're given.

## Ground rules

- This is a **live event tool**. Correctness of validation logic and
  reliability matter more than visual polish. A team must never be able to
  get an invalid route accepted, and a valid route must never be wrongly
  rejected.
- Backend: Python preferred (Flask + SQLite is the reference stack in the
  PRD) — deviate only if you have a good reason, and log why in `logs.md`.
- Server-side validation only. Never trust a client-submitted score —
  always recompute from the graph + submitted path.
- Where the PRD lists an "Open Question" with a stated default, proceed with
  the default rather than stopping to ask, but flag your choice in
  `logs.md` so Rudra can override later.
- Build in the milestone order from `PRD.md` §12. Don't start the frontend
  before the graph generator + reference solver prove the graph is solvable
  and has a genuine "shortest ≠ best" trap scenario — that's the whole point
  of the game and it's cheap to verify early, expensive to discover broken
  after the frontend is built.
- After each milestone: run it, actually test it (curl the endpoints, run
  the solver, open the page), and only then log it as done in `logs.md`.
  Don't mark something done on the basis that the code compiles.
- Keep the stack lightweight — this needs to run reliably on venue WiFi with
  15–30 concurrent teams on a free/cheap host or a laptop-as-LAN-server
  fallback. Avoid heavy frameworks or dependencies that complicate that.
- **You may be working alongside Claude Code sessions on the same codebase
  at different times.** Don't assume you're the only agent that has touched
  this repo — always check `logs.md` and the actual current state of the
  files (don't trust a stale plan) before continuing work.
- If you hit a decision not covered by the PRD, make a reasonable call,
  write it down in `logs.md` with your reasoning, and keep moving — don't
  block waiting for Rudra unless it's something that changes the game's
  fairness or the event-day plan materially.

## When you're done with a session

Always leave `logs.md` in a state where the *next* session — Gemini or
Claude Code, it won't have memory of this one — can read it and know
exactly: what's built, what's tested, what's broken, and what to do next.
Treat that handoff as part of the deliverable, not an afterthought.
