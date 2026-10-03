import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GAME_DIR = ROOT / "game"
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import db
import app as game_app

# Postgres migration: there's no per-test SQLite file to swap in anymore
# (db.DB_PATH doesn't exist — see game/db.py). Tests now run against
# whatever DATABASE_URL is set (a real Postgres, e.g. a Supabase project —
# use a throwaway/dev one, never production), with every table truncated
# before each test so tests stay isolated despite sharing one database.
_TABLES = [
    "submissions",
    "teams",
    "compromised_nodes",
    "team_compromised_nodes",
    "gateway_outbox",
    "event_clock",
]


@pytest.fixture
def client(monkeypatch):
    """Flask client backed by a freshly truncated Postgres (DATABASE_URL)."""
    if not db.DATABASE_URL:
        pytest.skip("DATABASE_URL is not set — tests need a real Postgres (see DEPLOYMENT.md)")

    db.init_db()
    conn = db.get_conn()
    for table in _TABLES:
        conn.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
    conn.commit()
    conn.close()
    db.init_db()  # re-seed event_clock after the truncate

    game_app.app.config.update(TESTING=True)
    with game_app.app.test_client() as client:
        yield client
