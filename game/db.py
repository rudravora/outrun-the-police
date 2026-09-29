"""
SQLite persistence for "Outrun the Police". One shared DB file so state
(teams, submissions, compromised nodes, event clock) survives a server
restart — see claude.md ground rules.
"""
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "game.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    team_code TEXT PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_code TEXT NOT NULL,
    route_json TEXT NOT NULL,
    valid INTEGER NOT NULL,
    reason TEXT NOT NULL,
    time_total REAL,
    risk_total REAL,
    cost_total REAL,
    score REAL,
    submitted_at REAL NOT NULL,
    event_t REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS compromised_nodes (
    node_id TEXT PRIMARY KEY,
    set_by TEXT NOT NULL,
    set_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS event_clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    t REAL NOT NULL,
    running INTEGER NOT NULL,
    started_at REAL,
    updated_at REAL NOT NULL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # seed the single event_clock row if missing: stopped, t=0
    row = conn.execute("SELECT 1 FROM event_clock WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO event_clock (id, t, running, started_at, updated_at) VALUES (1, 0, 0, NULL, ?)",
            (time.time(),),
        )
    conn.commit()
    conn.close()


def current_event_t(conn=None):
    """
    Current event-clock minute. If running, computed live from started_at;
    if paused, the frozen t value. This is the single source of truth for
    'what time is it right now' used by every validation call.
    """
    close = conn is None
    conn = conn or get_conn()
    row = conn.execute("SELECT t, running, started_at FROM event_clock WHERE id = 1").fetchone()
    if row["running"]:
        elapsed_minutes = (time.time() - row["started_at"]) / 60.0
        t = row["t"] + elapsed_minutes
    else:
        t = row["t"]
    if close:
        conn.close()
    return t


def get_compromised(conn=None):
    close = conn is None
    conn = conn or get_conn()
    rows = conn.execute("SELECT node_id FROM compromised_nodes").fetchall()
    if close:
        conn.close()
    return {r["node_id"] for r in rows}


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
