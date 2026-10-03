# Deployment — Outrun the Police

This app is a Flask process backed by **Postgres** (`DATABASE_URL` —
e.g. a Supabase project). Two supported deploy shapes:

- **Vercel + Supabase** (recommended — serverless, no persistent-disk
  headaches): outbox draining happens opportunistically on real request
  traffic plus a once-daily Vercel Cron backstop, since a serverless
  function instance isn't alive between requests to run a background
  thread. See that section below.
- **Render / Railway** (a normal persistent process): still fully
  supported in parallel, same Postgres backend — these just run the app
  as a long-lived process instead of serverless functions. Covered after
  the Vercel section.

**SQLite is no longer supported at all, anywhere, including local dev.**
`DATABASE_URL` is required everywhere now — point it at a free Supabase
project, or a local Postgres, before running anything (`python game/db.py`
to just initialize the schema, or `python game/app.py` to run the server).

## Environment variables

| Variable | Required? | What it does if unset |
|---|---|---|
| `DATABASE_URL` | **Yes, always** | App raises on startup — there's no fallback. A Postgres connection string. **On Supabase, use the "Transaction pooler" string (port 6543), not the direct connection** — a serverless function opens a fresh connection on almost every invocation and will exhaust Supabase's direct-connection slots fast; the pooler is built for exactly this access pattern. |
| `ADMIN_TOKEN` | **Yes, before going live** | Defaults to `dev-admin-token` — anyone could hit the admin endpoints. Set a real secret. |
| `GATEWAY_BASE_URL` | Set once the organizer shares it | Gateway integration runs in no-op mode: budget/compromise reads just use local fallbacks, nothing is sent out. Safe default for testing, wrong for event day. |
| `GATEWAY_API_KEY` | Set once the organizer shares it | Same no-op behavior as above. |
| `GATEWAY_OPPORTUNISTIC_DRAIN_LIMIT` | No | Defaults to 3 — how many queued gateway events `/api/submit_route`/`/api/leaderboard` retry per request (see the Vercel section's "why this needed real rework" note below). |
| `CRON_SECRET` | **Yes, on Vercel** | Without it, `/api/cron/drain-outbox` always returns 401 — the daily outbox backstop silently never runs. Not used by Render/Railway (no cron endpoint needed there). |
| `BUDGET_DEFAULT` | Recommended | Fallback cost budget used when the gateway is unreachable/unconfigured. Pick a real number before the event, not whatever default is in the code. |
| `INTEGRATION_KEYS` | Only if another game still calls our old `/api/integration/*` endpoints directly | Format `game3:key1,game5:key2`. Leave unset once everyone's migrated to the central gateway. |
| `PORT` | No | Set automatically by Render/Railway/Vercel. Only needed manually for the laptop fallback. |
| `FLASK_DEBUG` | No | Leave unset in production. Set to `1` for local dev if you want the reloader. |

## Option 0 — Vercel + Supabase (recommended)

1. **Supabase**: create a free project at supabase.com. In
   **Project Settings → Database → Connection string**, copy the
   **Transaction pooler** string (port 6543) — not "Session pooler" or
   the direct connection. This is your `DATABASE_URL`.
2. **Vercel**: connect this GitHub repo (Vercel dashboard → **Add New →
   Project**), or `vercel link` + `vercel deploy` from the CLI. Vercel
   auto-detects the Flask app at `game/app.py`'s `app` via
   `pyproject.toml`'s `[tool.vercel] entrypoint = "game.app:app"` — no
   extra config needed for that part.
3. In the Vercel project's **Settings → Environment Variables**, set:
   `DATABASE_URL` (the pooler string from step 1), `ADMIN_TOKEN`,
   `CRON_SECRET` (any random 16+ char string — generate one, e.g.
   `openssl rand -hex 16`; Vercel automatically sends it as
   `Authorization: Bearer <CRON_SECRET>` on cron-triggered requests, see
   [Vercel's cron docs](https://vercel.com/docs/cron-jobs/manage-cron-jobs#securing-cron-jobs)),
   `BUDGET_DEFAULT`, and once you have them, `GATEWAY_BASE_URL` /
   `GATEWAY_API_KEY`.
4. Deploy. `vercel.json`'s `crons` entry registers the daily outbox-drain
   backstop automatically (`/api/cron/drain-outbox`, once a day —
   **Vercel's Hobby/free plan only allows once-per-day cron jobs**, this
   is already picked to fit that).
5. Confirm end-to-end against the **deployed** URL, not just locally:
   open `/admin`, log in, set the clock, mark a node compromised; open
   `/team`, submit a route, confirm accept/reject + the route-code panel
   render correctly against the live Supabase DB.

**Why this needed real rework, not just a deploy setting**: Vercel runs
this as stateless serverless functions with a read-only filesystem (except
`/tmp`, which doesn't persist between invocations) and no long-lived
background thread between requests — both of which the original
SQLite-file + drain-thread design depended on. The fix was swapping SQLite
for Postgres (`game/db.py`, psycopg2) and replacing the background drain
thread with opportunistic draining on real traffic
(`gateway_client.drain_some()`, called from the two highest-traffic
endpoints) plus the daily cron backstop above for quiet periods. See
`brain/logs.md`'s migration entry for the full decision trail.

## Option A — Render (`render.yaml` included)

1. Push this repo to GitHub (already done).
2. In the Render dashboard: **New → Blueprint**, point it at this repo. It
   reads `render.yaml` automatically and creates the web service.
3. Set `DATABASE_URL` (the Supabase pooler string, same as the Vercel
   section above — or Render's own managed Postgres if you'd rather keep
   everything on one platform), `ADMIN_TOKEN`, `BUDGET_DEFAULT`, and
   (once you have them from the organizer) `GATEWAY_BASE_URL` /
   `GATEWAY_API_KEY` — these are listed with `sync: false` in
   `render.yaml` on purpose, so they're entered once in the dashboard,
   never committed to the repo. `plan: free` is fine now — state lives in
   Postgres, not on Render's own disk, so a free-tier spin-down/redeploy
   no longer wipes anything (that was the old SQLite-era caveat; no
   persistent disk is needed or configured here anymore).
4. Deploy. Render gives you a `https://<name>.onrender.com` URL.
5. Confirm end-to-end against the **hosted** instance, not just locally:
   open `/admin`, log in, set the clock, mark a node compromised; open
   `/team`, log in as a test team, submit a route, confirm it's
   accepted/rejected correctly and the history/route-code panel renders.

## Option B — Railway

1. In the Railway dashboard: **New Project → Deploy from GitHub repo**,
   pick this repo. Railway auto-detects the `Procfile`.
2. Set `DATABASE_URL` plus the same env vars as the Render step above, in
   Railway's Variables tab. No volume needed — state lives in Postgres.
3. Deploy, get the generated `https://<name>.up.railway.app` URL, run the
   same end-to-end check as Render step 5.

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

## Local development

`DATABASE_URL` is required even locally now — point it at a free Supabase
project (same pooler-string guidance as above) or a local Postgres
install. Then: `python game/db.py` to initialize the schema, or
`FLASK_DEBUG=1 python game/app.py` to run the dev server.

See `tests/RUNBOOK.md` for event-day admin-panel operation and
`tests/generate_team_codes.py` for pre-registering teams.
