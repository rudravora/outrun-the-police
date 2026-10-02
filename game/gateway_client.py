"""
Client for the CODEVERSE 2.0 central gateway (see
brain/GATEWAY-INTEGRATION-SPEC.md). This supersedes our own
game/integration_auth.py-gated endpoints as the real cross-game path — see
brain/logs.md for the migration note. Our existing /api/integration/*
endpoints are left in place (other games may still be mid-switch) but
nothing new is built on top of them.

Config: GATEWAY_BASE_URL, GATEWAY_API_KEY env vars. The real base URL/key/
test team T00 aren't shared yet (per the spec's §6 timeline) — point
GATEWAY_BASE_URL at a local mock for now (see game/gateway_mock.py). If
either env var is unset, this module is a no-op: send_event() queues to the
local outbox only (never calls out), get_team_state() always returns None.
That keeps local dev/testing working exactly as before this integration.

team_id: our existing team_code is used as-is (confirmed with the gateway
owner — no mapping table needed, unlike the spec's T01/T07/T00 examples).
game_id: "p2g4" (us, per spec §2).
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import db

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "").rstrip("/")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")
GAME_ID = "p2g4"
TIMEOUT_SECONDS = 3
DRAIN_INTERVAL_SECONDS = float(os.environ.get("GATEWAY_DRAIN_INTERVAL", "15"))  # spec: 10-30s

# Spec §5: "ONE event for EACH wrong submission" — ambiguous for us (unlike
# p2g1/p2g3 where the spec explicitly calls it out), so this ships off.
# Flip to true only once confirmed with the gateway owner (see logs.md).
SEND_WRONG_ATTEMPTS = os.environ.get("SEND_WRONG_ATTEMPTS", "false").lower() == "true"

log = logging.getLogger("gateway_client")
_warned_not_configured = False


def _configured():
    global _warned_not_configured
    if GATEWAY_BASE_URL and GATEWAY_API_KEY:
        return True
    if not _warned_not_configured:
        log.warning(
            "GATEWAY_BASE_URL/GATEWAY_API_KEY not set — gateway_client is a no-op "
            "(events queue locally only, get_team_state always returns None)."
        )
        _warned_not_configured = True
    return False


def _headers():
    return {"X-Game-Key": GATEWAY_API_KEY, "Content-Type": "application/json"}


def _build_event_body(event_type, team_id, points, money_delta, risk, meta):
    return {
        "event_id": str(uuid.uuid4()),
        "game_id": GAME_ID,
        "team_id": team_id,
        "type": event_type,
        "points": points,
        "money_delta": money_delta,
        "risk": risk,
        "meta": meta or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _request(method, url, body=None):
    """stdlib HTTP helper: JSON in, JSON out, raises urllib.error.HTTPError/
    URLError/socket.timeout on failure (caller decides retry/fallback)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_event(body):
    """Raw POST to /api/events. Returns True on success (2xx, including a
    409 duplicate — spec says treat that as success)."""
    try:
        _request("POST", f"{GATEWAY_BASE_URL}/api/events", body)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return True  # duplicate event_id — spec: treat as success
        raise


def send_event(event_type, team_id, points=0, money_delta=0, risk=None, meta=None):
    """
    Fire-and-forget: builds the event body per spec and tries to deliver it
    immediately. On ANY failure (not configured, timeout, connection error,
    5xx, unexpected error) the event is queued in the local SQLite outbox
    instead — this function never raises, so a submission (or any other
    caller) can never fail because the gateway is unreachable. Per spec §2
    rule 7, the outbox IS the required local log of accepted events.
    """
    body = _build_event_body(event_type, team_id, points, money_delta, risk, meta)
    body_json = json.dumps(body)

    if not _configured():
        db.outbox_enqueue(body["event_id"], body_json)
        return

    try:
        _post_event(body)
    except Exception as e:
        log.warning("gateway send_event(%s) failed, queuing: %s", event_type, e)
        db.outbox_enqueue(body["event_id"], body_json)


def get_team_state(team_id):
    """
    GET /api/teams/{team_id}/state. Returns the parsed dict
    ({team_id, status, balance, unlocked, outputs, compromised_nodes}) on
    success, or None on ANY failure (not configured, timeout, connection
    error, non-2xx, bad JSON) — callers must treat None as "unknown, use
    your own fallback," never raise up into request handling.
    """
    if not _configured():
        return None
    try:
        return _request("GET", f"{GATEWAY_BASE_URL}/api/teams/{team_id}/state")
    except Exception as e:
        log.warning("gateway get_team_state(%s) failed: %s", team_id, e)
        return None


def drain_outbox_once():
    """One retry pass over queued outbox events. Returns (delivered_count,
    remaining_count). Safe to call even when not configured (returns
    immediately — nothing to deliver to)."""
    if not _configured():
        return 0, len(db.outbox_pending())

    pending = db.outbox_pending()
    delivered = 0
    for row in pending:
        body = json.loads(row["body_json"])
        try:
            _post_event(body)
            db.outbox_mark_delivered(row["event_id"])
            delivered += 1
        except Exception as e:
            log.warning("gateway outbox retry failed for %s: %s", row["event_id"], e)
            db.outbox_mark_attempt(row["event_id"])
    return delivered, len(pending) - delivered


def start_drain_thread():
    """Starts a simple daemon thread that retries the outbox every
    DRAIN_INTERVAL_SECONDS (spec: 10-30s). Intentionally simple — one
    thread, no pooling/backoff — this is a one-event-every-few-seconds
    workload, not a high-throughput queue."""
    def loop():
        while True:
            time.sleep(DRAIN_INTERVAL_SECONDS)
            try:
                drain_outbox_once()
            except Exception as e:
                log.warning("gateway drain loop error: %s", e)

    t = threading.Thread(target=loop, name="gateway-outbox-drain", daemon=True)
    t.start()
    return t
