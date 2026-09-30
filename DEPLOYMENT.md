# Deployment — Outrun the Police

## Chosen host

Railway is the deployment target for the current SQLite-backed implementation.

The application writes its database to `game/game.db`. Railway Volumes provide
persistent storage across deployments and restarts, so the volume is mounted at
`/data` and `deploy/start.sh` links `game/game.db` to `/data/game.db`.

Do not mount the volume at `/app/game`: that directory contains the application
code. The persistent volume is intentionally mounted separately.

## Repository layout

The deployment expects this structure:

```text
/
├── Procfile
├── requirements.txt
├── deploy/
│   └── start.sh
├── game/
│   ├── app.py
│   ├── db.py
│   ├── solver.py
│   ├── graph.json
│   └── templates/
└── tests/
```

## Dependencies

The root `requirements.txt` pins the production dependencies:

- Flask 3.1.3
- Gunicorn 26.2.0

The existing `game/requirements.txt` can remain for local development.

## Railway setup

1. Create a Railway project and deploy the GitHub repository.
2. Let Railway detect the Python application.
3. Set the service start command to:

```text
sh deploy/start.sh
```

The same command is also recorded in the root `Procfile`.
4. Add the environment variable:

```text
ADMIN_TOKEN=<strong-random-secret>
```

Never commit the real admin token to Git.
5. Attach a Railway Volume to the application service.
6. Set the volume mount path to:

```text
/data
```

7. Keep the service at **one replica**. SQLite is a single-file database and the
Railway volume is attached to one service instance.
8. Generate a public Railway domain.
9. Optionally configure a health check against:

```text
/api/graph
```

The endpoint is unauthenticated and returns the graph/event state.

## First-deploy verification

After deployment, verify:

```text
GET /api/graph
```

Then use the real admin token to verify:

```text
GET /api/leaderboard
GET /api/admin/submissions
GET /api/admin/export
GET /api/admin/export.csv
```

Submit one known-valid test route:

```json
{
  "team_code": "DEPLOY-TEST",
  "route": ["N00", "N03", "N07", "N59"]
}
```

The submission should be accepted.

## Persistence verification

Do not consider deployment complete until this test has been performed against
the hosted service:

1. Set the event clock to a known value through the admin endpoint.
2. Submit a known-valid route.
3. Compromise a node.
4. Confirm the resulting state through the admin endpoints.
5. Restart/redeploy the service.
6. Confirm that the event clock, compromised node, submission, and leaderboard
   state are still present.

This verifies the Railway volume is actually being used by SQLite.

## Production process

Railway runs the Flask application through Gunicorn rather than Flask's
development server:

```text
gunicorn --chdir game app:app
```

`deploy/start.sh` performs the SQLite-volume setup first and then starts
Gunicorn.

## SQLite / scaling constraint

This deployment intentionally remains single-instance. Do not increase the
service to multiple replicas while SQLite is the authoritative database.
Multiple application instances must not independently own the same SQLite state.

## Local fallback: venue LAN

If the hosted service is unavailable on event day:

1. Put the project on the designated venue laptop.
2. Install the dependencies:

```text
pip install -r requirements.txt
```

3. Set the admin token in the environment.
4. From the project root, start the Flask server:

```text
cd game
python app.py
```

5. Connect the participating machines to the same venue LAN.
6. Use the laptop's LAN IP with port `5050`.

Example:

```text
http://192.168.x.x:5050
```

The exact LAN IP and firewall configuration must be checked on the venue
machine before the event.

## Security checklist

- Use a strong random `ADMIN_TOKEN`.
- Never commit `.env` files or real secrets.
- Do not expose the SQLite file directly.
- Verify that admin endpoints reject missing/incorrect tokens.
- Verify the hosted admin panel before event start.
- Keep a local copy/export path available before the event begins.
