# API Contract — Outrun the Police, cross-game integration

> **Superseded (2026-10-02)**: this direct game-to-game contract is being
> replaced by the real central gateway — see
> `brain/GATEWAY-INTEGRATION-SPEC.md`. Per that spec, **games never call
> each other directly**; everything goes through the gateway's
> `POST /api/events` and `GET /api/teams/{id}/state`. The three endpoints
> below are **left running for now** (don't rely on them being removed
> suddenly) but we are not building anything new on this path, and other
> games should migrate to the gateway contract instead of integrating
> against this doc going forward. See brain/logs.md's 2026-10-02 entry for
> what we've built on the gateway side.

For developers of the other CODEVERSE 2.0 Phase 2 games who need to read
this game's results or trigger a compromise event. You don't need to know
anything about how "Outrun the Police" works internally to use this — just
the three endpoints below.

Base URL: `http://<host>:<port>` — Rudra will give you the real event host.
For local testing against a dev server, it's `http://127.0.0.1:5050`.

## Auth

Every endpoint below requires a header:

```
X-Game-Key: <your game's key>
```

Each calling game gets its own key, issued by us ahead of the event — not
one shared secret. If you don't have your key yet, ask Rudra. A missing or
wrong key gets you a `401`:

```json
{ "error": "unauthorized" }
```

This is separate from the admin token used by the organizer panel — you
never need that.

---

## 1. `GET /api/integration/leaderboard`

Every team's current best route and a time/risk/cost/budget/deadline
breakdown, plus whether they've got a valid route submitted yet at all.
Sorted best-first by `risk` (teams with no valid route yet are sorted
last).

> **Breaking change (2026-10-01):** this used to return a combined
> `best_score` field (a weighted time/risk/cost total). The scoring model
> changed — a route is now scored by **risk alone**, and must independently
> satisfy a time deadline and a cost budget or it's rejected outright. If
> your code reads `best_score`, switch it to `risk`.

**Request:** no body.

```
GET /api/integration/leaderboard
X-Game-Key: <your key>
```

**Response `200`:**

```json
[
  {
    "team_code": "TEAM1",
    "has_valid_route": true,
    "risk": 8.0,
    "time": 35.0,
    "cost": 22.0,
    "budget": 100.0,
    "deadline": 120
  },
  {
    "team_code": "TEAM7",
    "has_valid_route": false,
    "risk": null,
    "time": null,
    "cost": null,
    "budget": 100.0,
    "deadline": 120
  }
]
```

Lower `risk` is better. `budget`/`deadline` are the caps that team's best
route had to satisfy (`time <= deadline` and `cost <= budget`) — a route
breaking either cap never makes it into this leaderboard at all, it's
rejected at submission time, not penalized in the risk value.

---

## 2. `GET /api/integration/result/<team_code>`

One team's current best **valid** submission — the actual route (list of
node IDs) plus its time/risk/cost breakdown. This is what you poll live
instead of waiting for an end-of-game export file.

> **Breaking change (2026-10-01):** the `score` field is gone — see the
> leaderboard note above, same model change. Use `risk`.

**Request:** no body. `<team_code>` in the URL, e.g. `TEAM1`.

```
GET /api/integration/result/TEAM1
X-Game-Key: <your key>
```

**Response `200`** (team has a valid route):

```json
{
  "team_code": "TEAM1",
  "has_valid_route": true,
  "route": ["N00", "N15", "N30", "N45", "N59"],
  "time": 35.0,
  "risk": 8.0,
  "cost": 22.0
}
```

**Response `404`** (team hasn't gotten a valid route accepted yet):

```json
{
  "team_code": "TEAM1",
  "has_valid_route": false
}
```

The result can change over time as a team resubmits and improves — poll
this whenever you need the latest, don't cache it for the whole event.

---

## 3. `POST /api/integration/compromise-trigger`

Report that a specific team's node should be treated as compromised — e.g.
a bad result in your game blocks one of that team's route options in this
game. **This only affects the named team**, not every team.

**Request:**

```
POST /api/integration/compromise-trigger
X-Game-Key: <your key>
Content-Type: application/json

{
  "team_code": "TEAM1",
  "node_id": "N15",
  "reason": "bad result in Game 3"
}
```

- `team_code` — required, the team whose node gets compromised.
- `node_id` — required, must be a real node ID in the map (ask Rudra for
  the node list, or pull `/api/graph` — that endpoint doesn't need a key).
- `reason` — optional free text, just for our audit log.

**Response `200`:**

```json
{
  "team_code": "TEAM1",
  "node_id": "N15",
  "compromised": true
}
```

**Response `400`** — missing `team_code` or an unrecognized `node_id`:

```json
{ "error": "unknown node N999" }
```

This takes effect immediately — the very next route that team submits
through that node gets rejected. It does not retroactively invalidate a
route they've already had accepted (their earlier score stands — see
"lock-in" in `PRD.md` §11.3).

---

## Notes

- All three endpoints are read/write against **live** state — there's no
  caching or delay on our end.
- ~~This key-based auth may be replaced later by a single key issued by a
  central cross-game gateway~~ — **this happened**, see the superseded
  notice at the top of this doc.
- Questions or a key you don't have yet: ask Rudra.

---

## Our outbound gateway behavior (informational, for the gateway owner)

Since 2026-10-02, we also act as a client of the central gateway (per
`brain/GATEWAY-INTEGRATION-SPEC.md`), in addition to running the endpoints
above. Not part of this doc's own contract — just flagging what to expect
from us on the other side:

- `GET /api/teams/{team_id}/state` — called on every route submission, to
  read `balance` (used as that team's cost budget) and `compromised_nodes`
  (merged into our own compromise checks). 3s timeout; on any failure we
  fall back to a local default budget and skip the gateway's compromised
  nodes — a submission never fails because the gateway is down.
- `POST /api/events` — `solved` (risk = route risk) on every accepted
  route; `output_issued` (meta.value = a short route code) when a team's
  best route improves. `wrong_attempt` is NOT currently sent (see
  brain/logs.md — ambiguous for us in the spec, open question). Failed
  sends queue locally and retry every ~15s until delivered; the same
  `event_id` may be retried (idempotent per spec §2.4).
- Points formula (`max(0, 1000 - risk*10)`) is a placeholder — **still
  open with the gateway owner**, see brain/logs.md.
