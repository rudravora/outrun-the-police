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

    db_file = test_game / "game.db"
    if db_file.exists():
        db_file.unlink()

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
        submitted_score = submission["breakdown"]["score"]
        assert submitted_score == 235.0

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
        assert submissions[0]["score"] == submitted_score

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
            {"team_code": "PERSIST-TEAM", "best_score": submitted_score}
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
        assert submissions[0]["score"] == submitted_score

    finally:
        stop_server(second)
