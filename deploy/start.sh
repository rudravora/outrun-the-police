#!/bin/sh
set -e

# Keep the existing application code unchanged while placing SQLite state
# on Railway's persistent volume.
mkdir -p /data
ln -sfn /data/game.db game/game.db

exec gunicorn --chdir game --bind 0.0.0.0:${PORT:-8000} app:app
