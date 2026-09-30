"""
Concurrent API load test for Outrun the Police.

Default:
    python load_test.py --teams 20

This starts the real Flask application in an isolated temporary copy of
game/, so the developer's game/game.db is not modified.

To test an already-running or deployed server explicitly:
    python load_test.py --teams 20 --base-url http://127.0.0.1:5050
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ADMIN_TOKEN = "load-test-token"
VALID_ROUTE = ["N00", "N03", "N07", "N59"]


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def request_json(base_url, method, path, body=None, headers=None):
    request_headers = dict(headers or {})
    data = None

    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, body
    except Exception as exc:
        return None, {"error": f"{type(exc).__name__}: {exc}"}


def wait_for_server(base_url, process):
    deadline = time.time() + 10

    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Flask server exited early with code {process.returncode}"
            )

        status, _ = request_json(base_url, "GET", "/api/graph")
        if status == 200:
            return

        time.sleep(0.1)

    raise TimeoutError("Flask server did not become ready within 10 seconds")


def start_isolated_server(project_root):
    temp_root = Path(tempfile.mkdtemp(prefix="outrun-load-test-"))
    source_game = project_root / "game"
    test_game = temp_root / "game"
    shutil.copytree(source_game, test_game)

    db_file = test_game / "game.db"
    if db_file.exists():
        db_file.unlink()

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

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

    process = subprocess.Popen(
        command,
        cwd=test_game,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return temp_root, process, base_url


def stop_server(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def submit_one(base_url, team_number, start_event):
    team_code = f"LOAD-{team_number:02d}"
    start_event.wait()

    started = time.perf_counter()
    status, body = request_json(
        base_url,
        "POST",
        "/api/submit_route",
        {"team_code": team_code, "route": VALID_ROUTE},
    )
    elapsed = time.perf_counter() - started

    return {
        "team_code": team_code,
        "status": status,
        "body": body,
        "elapsed": elapsed,
    }


def run_load_test(base_url, teams, admin_token):
    admin_headers = {"X-Admin-Token": admin_token}

    status, graph = request_json(base_url, "GET", "/api/graph")
    if status != 200:
        raise RuntimeError(
            f"Server health check failed: status={status}, body={graph}"
        )

    print(f"Target: {base_url}")
    print(f"Concurrent teams: {teams}")
    print(f"Event time: {graph.get('event_time')}")
    print(f"Route: {' -> '.join(VALID_ROUTE)}")
    print()
    print("Starting concurrent submissions...")

    start_event = threading.Event()
    results = []
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=teams) as executor:
        futures = [
            executor.submit(submit_one, base_url, i, start_event)
            for i in range(1, teams + 1)
        ]
        start_event.set()

        for future in as_completed(futures):
            results.append(future.result())

    total_elapsed = time.perf_counter() - started
    results.sort(key=lambda item: item["team_code"])

    successes = [r for r in results if r["status"] == 200]
    failures = [r for r in results if r["status"] != 200]

    print()
    print("Submission results")
    print("------------------")
    print(f"Successful: {len(successes)}/{teams}")
    print(f"Failed:     {len(failures)}/{teams}")
    print(f"Wall time:  {total_elapsed:.3f}s")

    latencies = [r["elapsed"] for r in results]
    if latencies:
        print(f"Min latency: {min(latencies):.3f}s")
        print(f"Max latency: {max(latencies):.3f}s")
        print(f"Avg latency: {sum(latencies) / len(latencies):.3f}s")

    if failures:
        print()
        print("Failures")
        print("--------")
        for result in failures:
            print(
                f"{result['team_code']}: "
                f"status={result['status']} body={result['body']}"
            )

    status, submissions = request_json(
        base_url,
        "GET",
        "/api/admin/submissions",
        headers=admin_headers,
    )

    print()
    print("Post-load persistence check")
    print("---------------------------")
    print(f"Admin submissions endpoint: HTTP {status}")

    recorded = set()
    if status == 200:
        recorded = {
            row["team_code"]
            for row in submissions
            if row["team_code"].startswith("LOAD-")
        }
        print(f"LOAD-* submissions recorded: {len(recorded)}/{teams}")

    leaderboard_status, leaderboard = request_json(
        base_url,
        "GET",
        "/api/leaderboard",
        headers=admin_headers,
    )

    print(f"Leaderboard endpoint: HTTP {leaderboard_status}")

    leaderboard_teams = set()
    if leaderboard_status == 200:
        leaderboard_teams = {
            row["team_code"]
            for row in leaderboard
            if row["team_code"].startswith("LOAD-")
        }
        print(f"LOAD-* teams on leaderboard: {len(leaderboard_teams)}/{teams}")

    print()

    if len(successes) != teams:
        raise SystemExit(
            "LOAD TEST FAILED: not every concurrent submission returned HTTP 200."
        )

    if status != 200 or len(recorded) != teams:
        raise SystemExit(
            "LOAD TEST FAILED: not every successful submission was persisted."
        )

    if leaderboard_status != 200 or len(leaderboard_teams) != teams:
        raise SystemExit(
            "LOAD TEST FAILED: not every successful team reached the leaderboard."
        )

    print("LOAD TEST PASSED: concurrent writes and post-load state checks succeeded.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--teams",
        type=int,
        default=20,
        help="Concurrent teams. Use 20 first, then 30.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Explicit existing server URL. Without this, an isolated local server is used.",
    )
    parser.add_argument(
        "--admin-token",
        default=ADMIN_TOKEN,
        help="Admin token for an explicit --base-url server.",
    )
    args = parser.parse_args()

    if not 15 <= args.teams <= 30:
        raise SystemExit("--teams must be between 15 and 30")

    project_root = Path(__file__).resolve().parent
    temp_root = process = None

    try:
        if args.base_url:
            run_load_test(
                args.base_url.rstrip("/"),
                args.teams,
                args.admin_token,
            )
        else:
            temp_root, process, base_url = start_isolated_server(project_root)
            wait_for_server(base_url, process)
            run_load_test(base_url, args.teams, ADMIN_TOKEN)
    finally:
        if process is not None:
            stop_server(process)
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
