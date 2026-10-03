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

Outbox draining: no background thread (removed in the Vercel/Postgres
migration — a serverless function instance isn't alive between requests,
so a thread sleeping between retries never actually runs). Instead:
drain_some() does a small bounded retry pass, called from high-traffic
endpoints (app.py's /api/submit_route, /api/leaderboard) so queued events
get retried on real traffic; drain_outbox_once() with no limit drains
everything, called once a day by GET/POST /api/cron/drain-outbox (meant
for Vercel Cron, see vercel.json) as a backstop for quiet periods.
"""
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import db

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "").rstrip("/")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")
GAME_ID = "p2g4"
TIMEOUT_SECONDS = 3

# No background thread on serverless hosting (a function instance isn't
# alive between requests) — outbox draining instead rides real traffic via
# drain_some(), a small bounded pass called from high-traffic endpoints.
OPPORTUNISTIC_DRAIN_LIMIT = int(os.environ.get("GATEWAY_OPPORTUNISTIC_DRAIN_LIMIT", "3"))

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


def drain_outbox_once(limit=None):
    """
    One retry pass over queued outbox events. `limit` bounds how many rows
    are attempted (None = drain everything — used by the daily cron
    backstop). Returns (delivered_count, remaining_count). Safe to call
    even when not configured (returns immediately — nothing to deliver to).
    Never raises.
    """
    if not _configured():
        return 0, len(db.outbox_pending(limit=limit))

    pending = db.outbox_pending(limit=limit)
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


def drain_some():
    """
    Opportunistic draining: a small bounded retry pass
    (OPPORTUNISTIC_DRAIN_LIMIT, default 3), meant to be called from
    high-traffic endpoints (/api/submit_route, /api/leaderboard) so the
    outbox gets retried on real traffic without a background thread. Never
    raises — any failure here must not break the request that triggered it.
    """
    try:
        drain_outbox_once(limit=OPPORTUNISTIC_DRAIN_LIMIT)
    except Exception as e:
        log.warning("gateway drain_some error: %s", e)
