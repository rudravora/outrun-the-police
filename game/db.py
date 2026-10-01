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
    event_t REAL NOT NULL,
    route_code TEXT
);

CREATE TABLE IF NOT EXISTS compromised_nodes (
    node_id TEXT PRIMARY KEY,
    set_by TEXT NOT NULL,
    set_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS team_compromised_nodes (
    team_code TEXT NOT NULL,
    node_id TEXT NOT NULL,
    set_by TEXT NOT NULL,
    set_at REAL NOT NULL,
    PRIMARY KEY (team_code, node_id)
);

CREATE TABLE IF NOT EXISTS event_clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    t REAL NOT NULL,
    running INTEGER NOT NULL,
    started_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS gateway_outbox (
    event_id TEXT PRIMARY KEY,
    body_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0,
    delivered_at REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at REAL
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
    """Global compromised-node set — admin-triggered, applies to every team."""
    close = conn is None
    conn = conn or get_conn()
    rows = conn.execute("SELECT node_id FROM compromised_nodes").fetchall()
    if close:
        conn.close()
    return {r["node_id"] for r in rows}


def get_team_compromised(team_code, conn=None):
    """Per-team compromised-node set. A node is blocked for this team if it's
    in EITHER this set or the global one — see effective_compromised()."""
    close = conn is None
    conn = conn or get_conn()
    rows = conn.execute(
        "SELECT node_id FROM team_compromised_nodes WHERE team_code = ?", (team_code,)
    ).fetchall()
    if close:
        conn.close()
    return {r["node_id"] for r in rows}


def effective_compromised(team_code, conn=None):
    """Union of the global list and this team's own list — what validation
    must actually check against for a given team's submission."""
    close = conn is None
    conn = conn or get_conn()
    result = get_compromised(conn) | get_team_compromised(team_code, conn)
    if close:
        conn.close()
    return result


def get_all_team_compromised(conn=None):
    """Every per-team compromise, for the admin panel's per-team view."""
    close = conn is None
    conn = conn or get_conn()
    rows = conn.execute(
        "SELECT team_code, node_id, set_by, set_at FROM team_compromised_nodes "
        "ORDER BY team_code, node_id"
    ).fetchall()
    if close:
        conn.close()
    return [dict(r) for r in rows]


def outbox_enqueue(event_id, body_json, conn=None):
    """Queue a gateway event body (already-serialized JSON string) for later
    delivery — used when a live POST to the gateway fails. INSERT OR IGNORE
    so re-enqueuing the same event_id (e.g. a retried call site) is a no-op,
    matching the gateway's own event_id idempotency."""
    close = conn is None
    conn = conn or get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO gateway_outbox (event_id, body_json, created_at, delivered) "
        "VALUES (?, ?, ?, 0)",
        (event_id, body_json, time.time()),
    )
    conn.commit()
    if close:
        conn.close()


def outbox_pending(conn=None):
    """Undelivered outbox events, oldest first."""
    close = conn is None
    conn = conn or get_conn()
    rows = conn.execute(
        "SELECT event_id, body_json, attempts FROM gateway_outbox "
        "WHERE delivered = 0 ORDER BY created_at ASC"
    ).fetchall()
    if close:
        conn.close()
    return [dict(r) for r in rows]


def outbox_mark_delivered(event_id, conn=None):
    close = conn is None
    conn = conn or get_conn()
    now = time.time()
    conn.execute(
        "UPDATE gateway_outbox SET delivered = 1, delivered_at = ?, "
        "attempts = attempts + 1, last_attempt_at = ? WHERE event_id = ?",
        (now, now, event_id),
    )
    conn.commit()
    if close:
        conn.close()


def outbox_mark_attempt(event_id, conn=None):
    """Record a failed retry attempt without marking delivered — keeps it
    queued for the next drain cycle."""
    close = conn is None
    conn = conn or get_conn()
    now = time.time()
    conn.execute(
        "UPDATE gateway_outbox SET attempts = attempts + 1, last_attempt_at = ? "
        "WHERE event_id = ?",
        (now, event_id),
    )
    conn.commit()
    if close:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
