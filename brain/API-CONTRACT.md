# API Contract — Outrun the Police, cross-game integration

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

Every team's current best score and a time/risk/cost breakdown, plus
whether they've got a valid route submitted yet at all. Sorted best-first
(teams with no valid route yet are sorted last).

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
    "best_score": 78.0,
    "time": 35.0,
    "risk": 8.0,
    "cost": 22.0
  },
  {
    "team_code": "TEAM7",
    "has_valid_route": false,
    "best_score": null,
    "time": null,
    "risk": null,
    "cost": null
  }
]
```

Lower `best_score` is better (it's a weighted time/risk/cost total —
you don't need the weights, just treat it as "lower = they did better").

---

## 2. `GET /api/integration/result/<team_code>`

One team's current best **valid** submission — the actual route (list of
node IDs) plus its score breakdown. This is what you poll live instead of
waiting for an end-of-game export file.

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
  "cost": 22.0,
  "score": 78.0
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
- This key-based auth may be replaced later by a single key issued by a
  central cross-game gateway, if the event ends up building one (still
  being decided). If that happens, only the auth header value changes —
  the request/response shapes above won't.
- Questions or a key you don't have yet: ask Rudra.
