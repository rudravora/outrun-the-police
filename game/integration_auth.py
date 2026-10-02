"""
Auth for the other CODEVERSE games calling our integration endpoints.

Current design: one API key per calling game, issued by us, config'd here as
a simple game_name -> key map (not hardcoded per-route, not one shared
secret). If the event ends up building a central cross-game gateway (still
being decided elsewhere), that gateway may issue a single key instead — this
module is the one place that would change; callers just use require_game_key().

Keys come from the INTEGRATION_KEYS env var: "game3:abc123,game5:def456".
Falls back to a dev default so local testing works without env setup —
**must** be overridden via env var before the real event, same as ADMIN_TOKEN.
"""
import os

from flask import request, jsonify

_DEFAULT_KEYS = "game3:dev-game3-key,game5:dev-game5-key"


def _load_keys():
    raw = os.environ.get("INTEGRATION_KEYS", _DEFAULT_KEYS)
    keys = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, _, key = pair.partition(":")
        if name and key:
            keys[key] = name
    return keys


_KEYS_BY_VALUE = _load_keys()


def require_game_key():
    """Checks X-Game-Key header against issued keys. Returns None if ok, else
    a (response, status) tuple to return directly from the route. On success,
    the calling game's name is available via request.game_name."""
    key = request.headers.get("X-Game-Key")
    game_name = _KEYS_BY_VALUE.get(key)
    if not game_name:
        return jsonify({"error": "unauthorized"}), 401
    request.game_name = game_name
    return None
