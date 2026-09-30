#!/bin/sh
set -e

mkdir -p /data
ln -sfn /data/game.db game/game.db

cd game
python -c "import db; db.init_db()"

exec gunicorn --bind 0.0.0.0:${PORT:-8000} app:app