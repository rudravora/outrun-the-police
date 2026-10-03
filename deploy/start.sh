#!/bin/sh
# Not referenced by render.yaml or Procfile (both call gunicorn directly) —
# kept as an alternate manual-start script. Updated for the Postgres
# migration: no more SQLite-file symlink/disk setup, DATABASE_URL (Postgres)
# must already be set in the environment before running this.
set -e

cd game
python -c "import db; db.init_db()"

exec gunicorn --bind 0.0.0.0:${PORT:-8000} app:app