"""
Minimal local mock of the CODEVERSE 2.0 central gateway (see
brain/GATEWAY-INTEGRATION-SPEC.md), for testing gateway_client.py before the
real base URL/key/test team are shared. NOT part of the real game — run
standalone, point GATEWAY_BASE_URL at it.

Usage: .venv/bin/python game/gateway_mock.py  (listens on :5099)
"""
import logging
from flask import Flask, jsonify, request

app = Flask(__name__)
log = logging.getLogger("werkzeug")

MOCK_API_KEY = "mock-gateway-key"
EVENTS = []  # in-memory log of accepted events, for test assertions
SEEN_EVENT_IDS = set()

# Fixed test state per spec §3B example shape — mutable at test time via
# /mock/set_state so a test can exercise budget/compromised-node merging.
TEAM_STATE = {
    "balance": 25.0,
    "unlocked": ["p1g1", "p1g2"],
    "outputs": {},
    "compromised_nodes": [],
}


def _check_key():
    return request.headers.get("X-Game-Key") == MOCK_API_KEY


@app.route("/api/events", methods=["POST"])
def events():
    if not _check_key():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    event_id = body.get("event_id")
    if event_id in SEEN_EVENT_IDS:
        return jsonify({"ok": True, "balance": TEAM_STATE["balance"]}), 409
    SEEN_EVENT_IDS.add(event_id)
    EVENTS.append(body)
    return jsonify({"ok": True, "balance": TEAM_STATE["balance"]})


@app.route("/api/teams/<team_id>/state", methods=["GET"])
def team_state(team_id):
    if not _check_key():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"team_id": team_id, "status": "active", **TEAM_STATE})


# --- test-only helpers, not part of the real gateway contract ---

@app.route("/mock/events", methods=["GET"])
def mock_events():
    return jsonify(EVENTS)


@app.route("/mock/set_state", methods=["POST"])
def mock_set_state():
    body = request.get_json(silent=True) or {}
    TEAM_STATE.update(body)
    return jsonify(TEAM_STATE)


@app.route("/mock/reset", methods=["POST"])
def mock_reset():
    EVENTS.clear()
    SEEN_EVENT_IDS.clear()
    TEAM_STATE.update({"balance": 25.0, "unlocked": ["p1g1", "p1g2"], "outputs": {}, "compromised_nodes": []})
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(port=5099)
