import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "game") not in sys.path:
    sys.path.insert(0, str(ROOT / "game"))
import db as _db  # noqa: E402 (after sys.path tweak, matches conftest.py's pattern)


ADMIN_TOKEN = "persistence-test-token"
ADMIN_HEADERS = {"X-Admin-Token": ADMIN_TOKEN}
VALID_ROUTE = ["N00", "N03", "N07", "N59"]


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def request_json(base_url, method, path, body=None, headers=None):
    data = None
    request_headers = dict(headers or {})

    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read().decode()
        return response.status, json.loads(raw) if raw else None


def wait_for_server(base_url, process):
    deadline = time.time() + 10

    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Flask server exited early with code {process.returncode}"
            )

        try:
            status, _ = request_json(base_url, "GET", "/api/graph")
            if status == 200:
                return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)

    raise TimeoutError("Flask server did not become ready within 10 seconds")


def start_server(game_dir, port):
    env = os.environ.copy()
    env["ADMIN_TOKEN"] = ADMIN_TOKEN
    env["PYTHONUNBUFFERED"] = "1"

    command = [
        sys.executable,
        "-c",
        (
            "import app; "
            "app.db.init_db(); "
            f"app.app.run(debug=False, host='127.0.0.1', port={port})"
        ),
    ]

    return subprocess.Popen(
        command,
        cwd=game_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_server(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_state_survives_real_server_restart(tmp_path):
    source_game = Path(__file__).resolve().parents[1] / "game"
    test_game = tmp_path / "game"
    shutil.copytree(source_game, test_game)

    # Postgres migration: state now lives in DATABASE_URL, shared across
    # test runs (there's no longer a per-test SQLite file to just not
    # copy) — truncate before this test so "restart with a clean slate,
    # then confirm exactly what we wrote survives" still holds.
    if not _db.DATABASE_URL:
        import pytest
        pytest.skip("DATABASE_URL is not set — tests need a real Postgres (see DEPLOYMENT.md)")
    _db.init_db()
    _conn = _db.get_conn()
    for _table in ("submissions", "teams", "compromised_nodes", "team_compromised_nodes",
                   "gateway_outbox", "event_clock"):
        _conn.execute(f"TRUNCATE TABLE {_table} RESTART IDENTITY CASCADE")
    _conn.commit()
    _conn.close()
    _db.init_db()  # re-seed event_clock after the truncate

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    first = start_server(test_game, port)

    try:
        wait_for_server(base_url, first)

        status, clock = request_json(
            base_url,
            "POST",
            "/api/admin/clock",
            {"action": "set", "t": 10},
            ADMIN_HEADERS,
        )
        assert status == 200
        assert clock["event_time"] == 10.0

        status, submission = request_json(
            base_url,
            "POST",
            "/api/submit_route",
            {"team_code": "PERSIST-TEAM", "route": VALID_ROUTE},
        )
        assert status == 200
        assert submission["accepted"] is True
        submitted_risk = submission["breakdown"]["risk"]
        assert submitted_risk == 57

        status, compromise = request_json(
            base_url,
            "POST",
            "/api/admin/compromise",
            {"node_id": "N03", "compromised": True},
            ADMIN_HEADERS,
        )
        assert status == 200
        assert compromise["compromised"] is True

        # Confirm the state that will be tested has actually been written
        # before we terminate the first process.
        status, submissions = request_json(
            base_url,
            "GET",
            "/api/admin/submissions",
            headers=ADMIN_HEADERS,
        )
        assert status == 200
        assert len(submissions) == 1
        assert submissions[0]["team_code"] == "PERSIST-TEAM"
        assert submissions[0]["valid"] == 1
        assert submissions[0]["score"] == submitted_risk

    finally:
        stop_server(first)

    second = start_server(test_game, port)

    try:
        wait_for_server(base_url, second)

        status, graph = request_json(
            base_url,
            "GET",
            "/api/graph",
        )
        assert status == 200
        assert graph["event_time"] == 10.0
        assert "N03" in graph["compromised_nodes"]

        status, leaderboard = request_json(
            base_url,
            "GET",
            "/api/leaderboard",
            headers=ADMIN_HEADERS,
        )
        assert status == 200
        assert leaderboard == [
            {
                "team_code": "PERSIST-TEAM",
                "risk": submitted_risk,
                "time": 3,
                "cost": 8,
                "budget": 100.0,
                "deadline": 120,
                "has_valid_route": True,
            }
        ]

        status, submissions = request_json(
            base_url,
            "GET",
            "/api/admin/submissions",
            headers=ADMIN_HEADERS,
        )
        assert status == 200
        assert len(submissions) == 1
        assert submissions[0]["team_code"] == "PERSIST-TEAM"
        assert submissions[0]["valid"] == 1
        assert submissions[0]["score"] == submitted_risk
    finally:
        stop_server(second)
