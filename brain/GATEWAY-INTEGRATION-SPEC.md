CODEVERSE 2.0 – CENTRAL GATEWAY: FULL INTEGRATION GUIDE

=====================================
1. THE FLOW (big picture)
=====================================
- There is ONE central app, the "gateway" (the leaderboard app). It is the single source of truth.
- Games NEVER call each other. Every game only talks to the gateway.
- The gateway owns: the team list, each team's money, scores, outputs, wrong attempts, hints, and the leaderboard.

How data moves:
  Game  --(POST /api/events)-->  Gateway  --> stores it --> leaderboard updates
  Game  <--(GET /api/teams/{id}/state)--  Gateway   (only for games that need to read something)
  Final Extraction --(POST /api/verify)--> Gateway checks what the team typed vs. what was stored

Example: a team finishes Control Server. That game sends output_issued with the token. The gateway stores it. Later, the team types the token into Final Extraction. Final Extraction calls /verify. The gateway says valid or invalid and records any wrong attempt.

Teams do NOT talk to the gateway. Only the games (with their keys) and the organizers (admin) do.

=====================================
2. GLOBAL RULES (apply to ALL games)
=====================================
1) TEAM IDs: use ONLY codes from teams.json (T01, T02, ...). Never invent your own team ID or numbering. A team_id not in the list is rejected (404). If your game has its own login, map it to this code.
2) GAME IDs: p1g1 Vault Breach, p1g2 Alarm System, p1g3 Hidden Blueprint, p1g4 Leak + Mint Map, p1g5 Printing Press, p2g1 Money Trail, p2g2 Black Market, p2g3 Control Server, p2g4 Outrun the Police, p2g5 Final Extraction
3) AUTH: each game gets its own API key. Send it in header X-Game-Key. A key can only send events for its own game_id.
4) event_id: every event needs a unique id (uuid). Sending the same event_id again (a retry) is safe and counts once. A duplicate returns success.
5) TIME: send timestamps in ISO format UTC. The gateway also stamps its own received time.
6) RETRIES: if the gateway is down or slow (3 second timeout), do NOT stop your game. Put the event in a local queue and retry every 10-30 seconds until it goes through.
7) LOCAL LOG: every game must keep its own local log (file or db) of every accepted submission with team, time, and result. This is our backup. If the gateway dies, we re-import from these logs.
8) MONEY EXCEPTION: money spends fail closed. If Black Market cannot reach the gateway, it must refuse the purchase. Never sell on a guessed balance.
9) ERRORS you may see: 401 bad key, 403 this game can't send that event type, 404 unknown team, 409 duplicate event (treat as success), 422 insufficient_funds, 5xx gateway problem (retry).

=====================================
3. ENDPOINTS
=====================================
Base URL: <to be shared>    Header on every call: X-Game-Key: <your key>

---- A) POST /api/events   (EVERY game uses this) ----
Request body:
{
  "event_id": "uuid",
  "game_id": "p2g3",
  "team_id": "T07",
  "type": "solved | wrong_attempt | hint_used | spend | output_issued | compromise",
  "points": 0,
  "money_delta": 0,
  "risk": 0,
  "meta": {}
}
Response: {"ok": true, "balance": 4200}

Event types:
- solved: the team completed your game. Send points. Put time_taken_seconds and attempts in meta.
- wrong_attempt: ONE event for EACH wrong submission. Feeds the "incorrect attempts" penalty.
- hint_used: ONE event for EACH hint a team uses.
- spend: money_delta is NEGATIVE. Black Market only. If balance is too low you get 422 insufficient_funds and nothing is deducted.
- output_issued: the output of your game for this team, in meta.value (deletion key, token, route code, etc.).
- compromise: marks a location as compromised, meta.node = node id. Read by Outrun the Police.

---- B) GET /api/teams/{team_id}/state   (only games that need to read) ----
Response example:
{
  "team_id": "T07",
  "status": "active",
  "balance": 4200,
  "unlocked": ["p1g1","p1g2"],
  "outputs": {"p2g1": "present", "p2g3": "present"},
  "compromised_nodes": [12, 31]
}
Note: other games' output VALUES are not returned here (only whether they exist). Values are only checked through /verify.

---- C) POST /api/verify   (ONLY Final Extraction) ----
Request:
{"team_id":"T07","deletion_key":"...","shutdown_code":"...","control_token":"...","route_code":"..."}
Response: {"deletion_key":"valid","shutdown_code":"invalid","control_token":"valid","route_code":"valid"}
Every invalid field is logged as a wrong attempt by the gateway itself. Final Extraction does not need to send those.

---- D) GET /api/leaderboard   (big screen, no key) ----
Returns teams ranked with score breakdown. Also has an organizer view.

=====================================
4. WHAT EACH GAME MUST DO
=====================================

PHASE 1 – THE ROYAL MINT
(Phase 1 games send results only, unless noted. Each game sends solved, wrong_attempt and hint_used.)

p1g1 VAULT BREACH (Daksh)
- When the correct vault code is entered: send solved with points based on accuracy and speed, and meta.time_taken_seconds.
- Each wrong code: send wrong_attempt.
- Reads nothing.

p1g2 ALARM SYSTEM (Sanchit)
- When the fixed program passes all test cases: send solved with points (+ bonus for early completion), meta.tests_passed, meta.time_taken_seconds.
- Each failed run is NOT automatically a wrong attempt. Tell us: do you count failed test runs as wrong attempts, or only final submissions?
- Reads nothing.

p1g3 HIDDEN BLUEPRINT (Aaryan G, Aaryan D)
- When the team finds the blueprint: send solved + points.
- The sheet says it "unlocks information for the next challenge". If the next challenge (p1g4) needs that information, also send output_issued with meta.value, and p1g4 reads it from state. Tell us if this applies.

p1g4 LEAK + MINT MAP (Nishika)
- When a route is submitted: send solved with points based on how close to optimal it is, and risk = route risk.
- Allowed to submit multiple times? If yes, tell us which one counts (we suggest the best).
- Reads nothing, unless it needs the blueprint info from p1g3.

p1g5 PRINTING PRESS (Aaditya)
- When predictions are scored against the hidden test values: send solved with points based on prediction error, meta.error_value.
- Tell us how many submissions are allowed and which counts (best or last).
- Reads nothing.

PHASE 2 – THE ESCAPE

p2g1 ERASE THE MONEY TRAIL (Bhargav, Vedika)
- When the deletion key is validated: send output_issued with meta.value = the deletion key for that team, then solved.
- Each wrong key: send wrong_attempt.
- Deletion key is unique per team, correct? Teams write it down and type it into Final Extraction.

p2g2 BLACK MARKET (Balganesh)
- Entry fee and every purchase: send spend with a negative money_delta and meta.item.
- Before every purchase: call GET state and check balance. If you can't reach the gateway, refuse the purchase.
- Personalized inflation (price increases per team) is calculated by YOUR game. The gateway only holds the money.
- Money left at the end counts for the final score, so the gateway is the only place the balance lives.
- Shutdown Code: right now NOBODY owns it. If Black Market issues it, send output_issued with meta.value. Please confirm.

p2g3 FIND THE CONTROL SERVER (Ashok, Siddharth)
- When the team finds the real control server: send output_issued with meta.value = the control token, then solved.
- Each wrong token/endpoint submission: send wrong_attempt.
- Token unique per team?

p2g4 OUTRUN THE POLICE (Omkar, Rudra)
- Reads GET state: balance (if money limits routes) and compromised_nodes.
- On each accepted route: send solved with risk = route risk.
- For the team's best accepted route, send output_issued with meta.value = a short ROUTE CODE (a checksum of the route + risk), so teams can write it down. Teams cannot be expected to hand-copy a long node list.
- Which submission counts: best valid route (lowest risk).
- Compromise signals come from the gateway/organizers via compromised_nodes.

p2g5 FINAL EXTRACTION (Rutuja, Unnatee)
- Reads GET state to see the team's status, balance and which outputs exist.
- Teams type: Deletion Key + Shutdown Code + Control Token + Route Code.
- Call POST /api/verify. The gateway tells you which fields are valid. The gateway logs wrong attempts.
- On a successful extraction: send solved with meta.time_remaining_seconds. The gateway computes the final score from: money retained, time remaining, risk accumulated, incorrect attempts, hints used.
- Winners: top 3 teams by final extraction score.

=====================================
5. WHAT THE GATEWAY DOES (my side)
=====================================
- Holds teams.json and issues API keys per game.
- Stores every event (never edits history). Balance and totals are computed from events, so mistakes can be corrected by the organizers.
- Money safety: all spends are atomic. Two games can never corrupt a balance. Overdrafts are rejected.
- Provides the live leaderboard and an organizer panel (corrections, mark compromised nodes, start/stop event clock).
- Can re-import your local logs if it crashes mid-event.

=====================================
6. TIMELINE
=====================================
- Base URL, API keys and test team T00 shared by: <date>
- Test integration with T00 by: <date>
- Full dress rehearsal: <date>
- Event: <date>

=====================================
7. PLEASE REPLY WITH
=====================================
1. Your stack and where its hosted
2. When a team counts as "solved", points formula, max points
3. Multiple submissions: which one counts?
4. Your output format and whether it is unique per team (Phase 2 games)
5. Anything you need to READ from the gateway
6. Any problem using teams.json codes as the only team ID
7. When your game will be ready to test
8. Any concern or thing you'd change
