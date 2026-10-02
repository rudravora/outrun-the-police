# RUNBOOK — Outrun the Police

This is the operator-facing checklist for running Game 4 during the live event.

## 1. System at a glance

Production service:

`https://outrun-the-police-production.up.railway.app`

Admin panel:

`https://outrun-the-police-production.up.railway.app/admin`

Primary event-clock control:

**Admin panel → Set clock to this minute**

The live-event policy is to use `set`/jump-to-minute as the primary clock mechanism.
The Start/Pause controls are intended for testing or special recovery situations.

The backend is authoritative for route validation and scoring.

## 2. Before event day

### Deployment

Confirm:

- Railway service is online.
- Public `/api/graph` returns JSON.
- Admin panel opens.
- Admin authentication works.
- The Railway Volume is attached at `/data`.
- `ADMIN_TOKEN` is configured in Railway and is not committed to Git.
- A known-valid test submission succeeds.
- A Railway restart has already been tested and state survives it.
- JSON and CSV exports work.

Current staging/prod test team used during deployment:

`DEPLOY-TEST`

Remove or clearly quarantine any test data before the real event starts if organizers
want a clean leaderboard/export.

### Team codes

Prepare the registration CSV:

```text
team_name
Alpha
Beta
Gamma
```

Generate codes:

```text
python generate_team_codes.py --input registered_teams.csv --output team_codes.csv
```

Print/distribute only the generated team code to each team.

Keep the organizer copy of `team_codes.csv` private.

### Event schedule

Fill in the actual organizer schedule here before event day:

```text
Game start:      ______
Clock milestone: ______
Compromise 1:    ______
Clock milestone: ______
Compromise 2:    ______
Submission close: ______
Results export:   ______
Game 5 handoff:   ______
```

Do not invent event times on the day. Use the event's official schedule.

## 3. Start of the live game

At the official Game 4 start:

1. Open the admin panel.
2. Confirm the clock is at `t = 0`.
3. Confirm no nodes are compromised unless the official schedule says otherwise.
4. Confirm the graph endpoint is responding.
5. Confirm the team-facing frontend is using the production API.
6. Record the official start time.

Use the admin panel's **Set clock to this minute** control to move the event clock
to the official minute.

## 4. Normal live operation

Watch:

- leaderboard
- live submissions
- accepted/rejected status
- score
- event time

Auto-refresh should remain enabled.

The event clock should normally be advanced using the **Set clock** field.

For a scheduled compromise:

1. Set the clock to the official event minute.
2. Click the designated node(s) in Compromised Nodes.
3. Confirm the node appears compromised.
4. Allow teams to refresh/fetch current graph state as required.

Do not modify graph generation, scoring, or solver behavior during the event.

## 5. Understanding a team report

If a team says:

> "Our route should be valid, but it was rejected."

Do not immediately change anything.

Check, in this order:

### A. Team code

Confirm the submitted team code matches the code issued at registration.

### B. Route

Look at the route shown in Live Submissions.

Check for:

- missing node
- wrong node order
- nonexistent edge
- accidental repeated/mistyped node ID

### C. Event time

Check the event clock at the exact `event_t` recorded for the submission.

An edge may have been valid earlier and closed later.

### D. Compromised nodes

Check whether the submitted route passed through a node compromised before that
submission.

Remember the project's grandfathering rule: a previously accepted submission is
not retroactively invalidated merely because a later compromise changes current
validation state. Only future submissions are evaluated against the new state.

### E. Submission record

Open Live Submissions and identify the exact rejection reason.

Do not diagnose from the team's recollection alone.

If there is a genuine platform bug, record:

- team code
- approximate event time
- exact route
- exact rejection reason
- screenshot if useful

Then escalate to the technical owner.

## 6. Clock recovery

If the organizer falls behind or the event needs to skip ahead:

1. Use **Set clock to this minute**.
2. Enter the official event minute.
3. Confirm the displayed clock.
4. Continue from that state.

For example:

```text
Current: 18.4
Official recovery point: 25
Set clock: 25
```

Do not use repeated Start/Pause clicks to simulate the official event timeline.

## 7. If Railway appears unhealthy

First check:

```text
Railway service status
Railway deployment logs
Public /api/graph
```

Then check the admin panel.

If the hosted service cannot be restored quickly, use the LAN fallback described
below.

Do not repeatedly redeploy during the live event unless the technical owner has
confirmed it is safe.

## 8. Venue LAN fallback

The game can run from a designated venue laptop if internet hosting fails.

On the fallback laptop:

```text
pip install -r requirements.txt
```

Set the admin token.

From the project root:

```text
cd game
python app.py
```

Find the laptop's LAN IP and give teams the corresponding server address:

```text
http://<LAPTOP-LAN-IP>:5050
```

Before using the fallback live:

- confirm venue machines can reach the laptop
- check Windows firewall/network profile
- open `/api/graph`
- open `/admin`
- confirm admin authentication
- perform one known-valid test submission

Use the same operational rules for clock and compromises.

## 9. Closing the game

At the official submission close:

1. Set/confirm the clock at the official closing minute.
2. Stop treating new submissions as part of the live competition according to the
   event's finalized rules.
3. Refresh the leaderboard.
4. Review the live submissions for obvious operational anomalies.
5. Export final JSON.
6. Export final CSV.
7. Save both artifacts somewhere safe.
8. Pass the final per-team risk values and other required outputs to the Game 5 owners.

The backend export is:

```text
/api/admin/export
/api/admin/export.csv
```

The export represents the best valid route per team.

## 10. Final handoff to Game 5

The key Game 4 output is keyed by:

```text
team_code
```

and includes the team's:

```text
best valid route
risk
time
cost
score
```

Game 5 owners should receive the final export rather than manually copying values.

Keep the original exported files unchanged as the event record.

## 11. After the event

Archive:

- final JSON export
- final CSV export
- relevant screenshots/logs
- list of team codes
- any incident notes

Do not commit secrets, admin tokens, or private organizer data to GitHub.

## 12. Important rules for operators

Do not:

- change the scoring formula during the event
- regenerate `graph.json`
- edit `solver.py`
- manually edit SQLite records unless the technical owner explicitly directs it
- publish the admin token
- treat a browser-side score as authoritative

Do:

- rely on server validation
- use the admin panel for event state
- inspect the recorded submission when resolving disputes
- export the final results before handoff
