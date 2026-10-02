# Deployment — Outrun the Police

This app is a plain Flask process backed by a SQLite file on disk, plus a
background thread that retries queued gateway events every
`GATEWAY_DRAIN_INTERVAL` seconds. Both of those need a host that runs it as
a normal persistent process with a normal filesystem — not a serverless
platform (see the note at the bottom on why Vercel-style hosting doesn't
fit this app without real rework).

Render and Railway both fit as-is. Instructions below cover Render first
(a ready `render.yaml` is included), then Railway as the alternative, then
the laptop-as-LAN-server fallback for event day if hosting has issues.

## Environment variables

| Variable | Required? | What it does if unset |
|---|---|---|
| `ADMIN_TOKEN` | **Yes, before going live** | Defaults to `dev-admin-token` — anyone could hit the admin endpoints. Set a real secret. |
| `GATEWAY_BASE_URL` | Set once the organizer shares it | Gateway integration runs in no-op mode: budget/compromise reads just use local fallbacks, nothing is sent out. Safe default for testing, wrong for event day. |
| `GATEWAY_API_KEY` | Set once the organizer shares it | Same no-op behavior as above. |
| `GATEWAY_DRAIN_INTERVAL` | No | Defaults to 15 (seconds between outbox retries). |
| `BUDGET_DEFAULT` | Recommended | Fallback cost budget used when the gateway is unreachable/unconfigured. Pick a real number before the event, not whatever default is in the code. |
| `INTEGRATION_KEYS` | Only if another game still calls our old `/api/integration/*` endpoints directly | Format `game3:key1,game5:key2`. Leave unset once everyone's migrated to the central gateway. |
| `DB_PATH` | Only matters on a host without a persistent disk mounted — see below | Defaults to a file inside the repo checkout. |
| `PORT` | No | Set automatically by Render/Railway. Only needed manually for the laptop fallback. |
| `FLASK_DEBUG` | No | Leave unset in production. Set to `1` for local dev if you want the reloader. |

## Option A — Render (recommended, `render.yaml` included)

1. Push this repo to GitHub (already done).
2. In the Render dashboard: **New → Blueprint**, point it at this repo. It
   reads `render.yaml` automatically and creates the web service plus a
   1GB persistent disk mounted at `/data`.
3. **This uses the `starter` plan (~$7/month), not free** — deliberately.
   Render's free tier has **no persistent disk**, and this app's whole
   state (teams, submissions, compromised nodes, the gateway outbox) is a
   SQLite file on disk. On free tier, every redeploy *and every spin-down
   restart* silently resets that file to empty. For a one-off dry run
   that's merely annoying; **for the live event, that's a team's entire
   progress wiped mid-game** — not worth the ~$7 saving. If you want to
   test without paying first, delete the `disk:` block and change
   `plan: starter` to `plan: free` in `render.yaml` — just don't use that
   config on event day.
4. In the Render dashboard, set `ADMIN_TOKEN`, `BUDGET_DEFAULT`, and
   (once you have them from the organizer) `GATEWAY_BASE_URL` /
   `GATEWAY_API_KEY` — these are listed with `sync: false` in
   `render.yaml` on purpose, so they're entered once in the dashboard,
   never committed to the repo.
5. Deploy. Render gives you a `https://<name>.onrender.com` URL.
6. Confirm end-to-end against the **hosted** instance, not just locally:
   open `/admin`, log in, set the clock, mark a node compromised; open
   `/team`, log in as a test team, submit a route, confirm it's
   accepted/rejected correctly and the history/route-code panel renders.

## Option B — Railway

1. In the Railway dashboard: **New Project → Deploy from GitHub repo**,
   pick this repo. Railway auto-detects the `Procfile`.
2. Add a **volume**, mount it at `/data`. Railway volumes persist across
   redeploys (same reason as Render's disk above).
3. Set `DB_PATH=/data/game.db` plus the same env vars as the Render table
   above, in Railway's Variables tab.
4. Deploy, get the generated `https://<name>.up.railway.app` URL, run the
   same end-to-end check as Render step 6.

## Option C — Laptop-as-venue-LAN-server fallback

If hosting has problems on event day, run it directly on a laptop
connected to the venue WiFi, with teams hitting it by LAN IP:

1. On the laptop: `cd game && pip install -r requirements.txt`
2. Find the laptop's LAN IP (`ip addr` / `ifconfig` on Linux/Mac, `ipconfig`
   on Windows) — e.g. `192.168.1.42`.
3. Set the real env vars (`ADMIN_TOKEN`, `BUDGET_DEFAULT`, and
   `GATEWAY_BASE_URL`/`GATEWAY_API_KEY` if the venue has internet to reach
   the real gateway — if not, leave them unset and the app degrades to
   local-fallback budgets with no gateway sends, per the no-op behavior
   above).
4. Run: `PORT=5050 python app.py`
5. Teams on the same WiFi open `http://192.168.1.42:5050/team` in a
   browser. Admin panel is the same host at `/admin`.
6. **Test this path before the event, not during it** — confirm a second
   device on the same WiFi can actually reach that URL (some venue WiFi
   configs isolate devices from each other, which would break this
   fallback silently).

## Why not Vercel

Vercel runs this kind of app as stateless serverless functions with a
read-only filesystem (except `/tmp`, which doesn't persist between
invocations) — that breaks the SQLite-file-on-disk assumption this app
relies on for state to survive a restart, and it doesn't support a
long-lived background thread (the gateway outbox drain loop) sitting
between requests. Making this Vercel-compatible would mean swapping
SQLite for a hosted Postgres and replacing the drain thread with a
scheduled Vercel Cron job — real rework, not a deploy setting. Render and
Railway both run this as a normal persistent process, so nothing about the
app needs to change.

## What's still not covered here

- No automated test suite yet (`tests/`) — see `brain/teammate-tasks.md`.
- No team-code generator script — same file.
- `RUNBOOK.md` for whoever runs the admin panel live — not written yet.
