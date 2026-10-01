"""
Flask backend for "Outrun the Police" (CODEVERSE 2.0, Phase 2 Game 4).

Team-facing:
  GET  /team                        -> team app UI (graph view, submission form, history)
  GET  /api/graph                   -> graph filtered by live clock + compromised nodes
  GET  /api/graph.json              -> raw generated graph.json (static download)
  GET  /api/graph.csv               -> raw generated graph.csv (static download)
  POST /api/submit_route            -> {team_code, route: [node ids]} -> accept/reject + score
  GET  /api/team/<team_code>/history -> that team's own submission history only
  GET  /api/leaderboard             -> standings (admin-only per PRD default, token-gated)

Admin (all require header X-Admin-Token matching ADMIN_TOKEN):
  GET  /admin                     -> admin panel UI (token entered client-side)
  POST /api/admin/compromise      -> {node_id, compromised: bool} (GLOBAL, all teams)
  POST /api/admin/team_compromise -> {team_code, node_id, compromised: bool} (this team only)
  GET  /api/admin/team_compromised -> full list of active per-team compromises
  POST /api/admin/clock           -> {action: start|pause|set, t: optional}
  GET  /api/admin/submissions     -> full submission log (valid + rejected)
  GET  /api/admin/export          -> best valid route per team, JSON
  GET  /api/admin/export.csv      -> same, CSV

Cross-game integration (all require header X-Game-Key, see integration_auth.py
and brain/API-CONTRACT.md for the full contract):
  GET  /api/integration/leaderboard        -> every team's best score + breakdown
  GET  /api/integration/result/<team_code> -> one team's current best valid route
  POST /api/integration/compromise-trigger -> {team_code, node_id, reason} -> per-team compromise

A node is blocked for a team's submission if it's in EITHER the global
compromised list OR that team's own per-team list (db.effective_compromised).
The global list is unchanged from before; the per-team list is additive.

Event-day clock policy: `action: set` (jump to a specific minute) is the
primary mechanism organizers use, matching how compromise events are
scripted/triggered live (see context.md walkthrough). `start`/`pause`
free-run the clock in real time (1 wall-minute = 1 event-minute) and exist
for testing only — the admin UI marks them as secondary for this reason.

All scoring/validation logic is imported from game/solver.py — never
reimplemented here, per claude.md (server-side validation, single source of
truth).
"""
import csv
import io
import json
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, Response, render_template, send_from_directory

import db
from integration_auth import require_game_key
from solver import load_graph, validate_path, path_totals, path_score

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")

app = Flask(__name__)
GRAPH = load_graph()
WEIGHTS = GRAPH["weights"]
GAME_DIR = Path(__file__).parent


def require_admin():
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        return jsonify({"error": "unauthorized"}), 401
    return None


def visible_graph(t, compromised):
    """
    Team-facing graph view: same nodes/edges, but each edge and node is
    annotated with whether it's currently usable, so teams don't have to
    re-derive clock/compromise logic client-side. The full time/risk/cost
    stats stay visible even for currently-closed edges (per PRD 8.2 — teams
    need to see the whole map to plan ahead of clock changes).
    """
    edges = []
    for e in GRAPH["edges"]:
        edges.append({
            **e,
            "open_now": e["window_start"] <= t <= e["window_end"],
        })
    nodes = [{"id": n["id"], "compromised": n["id"] in compromised} for n in GRAPH["nodes"]]
    return {
        "nodes": nodes,
        "edges": edges,
        "hideout": GRAPH["hideout"],
        "extraction": GRAPH["extraction"],
        "weights": WEIGHTS,
        "event_time": t,
        "event_duration": GRAPH["event_duration"],
        "compromised_nodes": sorted(compromised),
    }


@app.route("/admin", methods=["GET"])
def admin_panel():
    """
    Admin panel page. Separate route from anything teams see. The page
    itself has no server-side auth check (it's just static HTML/JS) — every
    data call it makes goes through the existing X-Admin-Token-gated API
    endpoints, so there's no admin data exposed without the correct token.
    """
    return render_template("admin.html")


@app.route("/team", methods=["GET"])
def team_app():
    """Team-facing app. No server-side auth (login is just a team code, no
    password per PRD 8.2) — the code is only ever used as the team_code
    param on /api/submit_route and /api/team/<code>/history, both of which
    are scoped to that code server-side."""
    return render_template("team.html")


@app.route("/api/graph.json", methods=["GET"])
def api_graph_json_download():
    """Raw generated graph.json (Milestone 1 source of truth), for teams who
    want the plain file instead of the rendered view."""
    return send_from_directory(GAME_DIR, "graph.json", mimetype="application/json")


@app.route("/api/graph.csv", methods=["GET"])
def api_graph_csv_download():
    return send_from_directory(GAME_DIR, "graph.csv", mimetype="text/csv")


@app.route("/api/graph", methods=["GET"])
def api_graph():
    conn = db.get_conn()
    t = db.current_event_t(conn)
    compromised = db.get_compromised(conn)
    conn.close()
    return jsonify(visible_graph(t, compromised))


@app.route("/api/submit_route", methods=["POST"])
def api_submit_route():
    body = request.get_json(silent=True) or {}
    team_code = body.get("team_code")
    route = body.get("route")

    if not team_code or not isinstance(team_code, str):
        return jsonify({"error": "team_code is required"}), 400
    if not isinstance(route, list) or not all(isinstance(n, str) for n in route):
        return jsonify({"error": "route must be a list of node id strings"}), 400

    conn = db.get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO teams (team_code, name) VALUES (?, ?)", (team_code, team_code)
    )

    t = db.current_event_t(conn)
    compromised = db.effective_compromised(team_code, conn)

    ok, reason, edges = validate_path(GRAPH, route, t=t, compromised=compromised)

    result = {
        "accepted": ok,
        "reason": reason,
        "route": route,
        "event_time": t,
    }

    time_total = risk_total = cost_total = score_val = None
    if ok:
        totals = path_totals(edges)
        score_val = path_score(edges, WEIGHTS)
        time_total, risk_total, cost_total = totals["time"], totals["risk"], totals["cost"]
        result["breakdown"] = {**totals, "score": score_val}

        # is this the team's new best valid submission? (lower score = better)
        best = conn.execute(
            "SELECT MIN(score) AS best_score FROM submissions WHERE team_code = ? AND valid = 1",
            (team_code,),
        ).fetchone()
        result["is_new_best"] = best["best_score"] is None or score_val < best["best_score"]

    conn.execute(
        """INSERT INTO submissions
           (team_code, route_json, valid, reason, time_total, risk_total, cost_total, score, submitted_at, event_t)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (team_code, json.dumps(route), int(ok), reason, time_total, risk_total, cost_total,
         score_val, time.time(), t),
    )
    conn.commit()
    conn.close()

    return jsonify(result), (200 if ok else 422)


@app.route("/api/team/<team_code>/history", methods=["GET"])
def api_team_history(team_code):
    """A team's own submission history only — no auth beyond knowing your
    own team_code (same trust model as submission itself, per PRD 8.2 'codes
    only'). Scoped by a WHERE team_code = ? clause, never returns other
    teams' rows."""
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT id, route_json, valid, reason, time_total, risk_total, cost_total,
                  score, submitted_at, event_t
           FROM submissions WHERE team_code = ? ORDER BY submitted_at DESC""",
        (team_code,),
    ).fetchall()
    conn.close()
    return jsonify([
        {
            "id": r["id"],
            "route": json.loads(r["route_json"]),
            "valid": bool(r["valid"]),
            "reason": r["reason"],
            "time": r["time_total"],
            "risk": r["risk_total"],
            "cost": r["cost_total"],
            "score": r["score"],
            "submitted_at": r["submitted_at"],
            "event_t": r["event_t"],
        }
        for r in rows
    ])


@app.route("/api/leaderboard", methods=["GET"])
def api_leaderboard():
    # Admin-only visibility per PRD §11 default 5.
    err = require_admin()
    if err:
        return err
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT team_code, MIN(score) AS best_score
           FROM submissions WHERE valid = 1
           GROUP BY team_code ORDER BY best_score ASC"""
    ).fetchall()
    conn.close()
    return jsonify([{"team_code": r["team_code"], "best_score": r["best_score"]} for r in rows])


@app.route("/api/admin/compromise", methods=["POST"])
def admin_compromise():
    err = require_admin()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    node_id = body.get("node_id")
    compromised = body.get("compromised", True)
    valid_ids = {n["id"] for n in GRAPH["nodes"]}
    if node_id not in valid_ids:
        return jsonify({"error": f"unknown node {node_id}"}), 400

    conn = db.get_conn()
    if compromised:
        conn.execute(
            "INSERT OR REPLACE INTO compromised_nodes (node_id, set_by, set_at) VALUES (?, ?, ?)",
            (node_id, "admin", time.time()),
        )
    else:
        conn.execute("DELETE FROM compromised_nodes WHERE node_id = ?", (node_id,))
    conn.commit()
    compromised_now = db.get_compromised(conn)
    conn.close()
    return jsonify({"node_id": node_id, "compromised": node_id in compromised_now})


@app.route("/api/admin/team_compromise", methods=["POST"])
def admin_team_compromise():
    """Per-team compromise layer — additive to the global list above, does
    not replace it. A node is blocked for a team if it's in EITHER list
    (see db.effective_compromised)."""
    err = require_admin()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    team_code = body.get("team_code")
    node_id = body.get("node_id")
    compromised = body.get("compromised", True)
    valid_ids = {n["id"] for n in GRAPH["nodes"]}
    if not team_code or not isinstance(team_code, str):
        return jsonify({"error": "team_code is required"}), 400
    if node_id not in valid_ids:
        return jsonify({"error": f"unknown node {node_id}"}), 400

    conn = db.get_conn()
    if compromised:
        conn.execute(
            "INSERT OR REPLACE INTO team_compromised_nodes (team_code, node_id, set_by, set_at) "
            "VALUES (?, ?, ?, ?)",
            (team_code, node_id, "admin", time.time()),
        )
    else:
        conn.execute(
            "DELETE FROM team_compromised_nodes WHERE team_code = ? AND node_id = ?",
            (team_code, node_id),
        )
    conn.commit()
    now_compromised = node_id in db.get_team_compromised(team_code, conn)
    conn.close()
    return jsonify({"team_code": team_code, "node_id": node_id, "compromised": now_compromised})


@app.route("/api/admin/team_compromised", methods=["GET"])
def admin_team_compromised_list():
    """All per-team compromises, for the admin panel's per-team view."""
    err = require_admin()
    if err:
        return err
    conn = db.get_conn()
    rows = db.get_all_team_compromised(conn)
    conn.close()
    return jsonify(rows)


@app.route("/api/admin/clock", methods=["POST"])
def admin_clock():
    err = require_admin()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    conn = db.get_conn()
    now = time.time()

    if action == "start":
        conn.execute(
            "UPDATE event_clock SET running = 1, started_at = ?, updated_at = ? WHERE id = 1",
            (now, now),
        )
    elif action == "pause":
        t = db.current_event_t(conn)
        conn.execute(
            "UPDATE event_clock SET running = 0, t = ?, started_at = NULL, updated_at = ? WHERE id = 1",
            (t, now),
        )
    elif action == "set":
        t = body.get("t")
        if t is None:
            conn.close()
            return jsonify({"error": "t is required for action=set"}), 400
        conn.execute(
            "UPDATE event_clock SET t = ?, started_at = ?, updated_at = ? WHERE id = 1",
            (float(t), now if body.get("keep_running") else None,
             now),
        )
        if not body.get("keep_running"):
            conn.execute("UPDATE event_clock SET running = 0 WHERE id = 1")
    else:
        conn.close()
        return jsonify({"error": "action must be start|pause|set"}), 400

    conn.commit()
    t_now = db.current_event_t(conn)
    conn.close()
    return jsonify({"event_time": t_now})


@app.route("/api/admin/submissions", methods=["GET"])
def admin_submissions():
    err = require_admin()
    if err:
        return err
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM submissions ORDER BY submitted_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


def _best_routes(conn):
    rows = conn.execute(
        """SELECT s.team_code, s.route_json, s.time_total, s.risk_total, s.cost_total, s.score
           FROM submissions s
           JOIN (
               SELECT team_code, MIN(score) AS best_score
               FROM submissions WHERE valid = 1 GROUP BY team_code
           ) b ON s.team_code = b.team_code AND s.score = b.best_score AND s.valid = 1
           GROUP BY s.team_code"""
    ).fetchall()
    return rows


@app.route("/api/admin/export", methods=["GET"])
def admin_export():
    err = require_admin()
    if err:
        return err
    conn = db.get_conn()
    rows = _best_routes(conn)
    conn.close()
    return jsonify([
        {
            "team_code": r["team_code"],
            "route": json.loads(r["route_json"]),
            "time": r["time_total"],
            "risk": r["risk_total"],
            "cost": r["cost_total"],
            "score": r["score"],
        }
        for r in rows
    ])


@app.route("/api/admin/export.csv", methods=["GET"])
def admin_export_csv():
    err = require_admin()
    if err:
        return err
    conn = db.get_conn()
    rows = _best_routes(conn)
    conn.close()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["team_code", "route", "time", "risk", "cost", "score"])
    for r in rows:
        w.writerow([r["team_code"], " -> ".join(json.loads(r["route_json"])),
                    r["time_total"], r["risk_total"], r["cost_total"], r["score"]])
    return Response(buf.getvalue(), mimetype="text/csv")


def _best_row_for_team(conn, team_code):
    return conn.execute(
        """SELECT team_code, route_json, time_total, risk_total, cost_total, score
           FROM submissions WHERE team_code = ? AND valid = 1
           ORDER BY score ASC LIMIT 1""",
        (team_code,),
    ).fetchone()


@app.route("/api/integration/leaderboard", methods=["GET"])
def integration_leaderboard():
    """Cross-game read: every team's best score + breakdown + whether they
    have a valid route yet. Gated by a per-game API key (X-Game-Key), not
    the admin token — see integration_auth.py. Documented in
    brain/API-CONTRACT.md."""
    err = require_game_key()
    if err:
        return err
    conn = db.get_conn()
    team_codes = [r["team_code"] for r in conn.execute("SELECT team_code FROM teams").fetchall()]
    out = []
    for team_code in team_codes:
        best = _best_row_for_team(conn, team_code)
        out.append({
            "team_code": team_code,
            "has_valid_route": best is not None,
            "best_score": best["score"] if best else None,
            "time": best["time_total"] if best else None,
            "risk": best["risk_total"] if best else None,
            "cost": best["cost_total"] if best else None,
        })
    conn.close()
    out.sort(key=lambda r: (r["best_score"] is None, r["best_score"]))
    return jsonify(out)


@app.route("/api/integration/result/<team_code>", methods=["GET"])
def integration_result(team_code):
    """Cross-game read: one team's current best valid submission (route +
    score breakdown). Same X-Game-Key auth as the leaderboard above. This is
    what Game 5 polls live instead of waiting for the end-of-game export."""
    err = require_game_key()
    if err:
        return err
    conn = db.get_conn()
    best = _best_row_for_team(conn, team_code)
    conn.close()
    if best is None:
        return jsonify({"team_code": team_code, "has_valid_route": False}), 404
    return jsonify({
        "team_code": team_code,
        "has_valid_route": True,
        "route": json.loads(best["route_json"]),
        "time": best["time_total"],
        "risk": best["risk_total"],
        "cost": best["cost_total"],
        "score": best["score"],
    })


@app.route("/api/integration/compromise-trigger", methods=["POST"])
def integration_compromise_trigger():
    """Cross-game write: another game (e.g. Game 3) reports a team's node as
    compromised. Writes into the per-team compromised list (not the global
    one) so it only affects that team, and takes effect on that team's very
    next submission check via db.effective_compromised()."""
    err = require_game_key()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    team_code = body.get("team_code")
    node_id = body.get("node_id")
    reason = body.get("reason", "")
    valid_ids = {n["id"] for n in GRAPH["nodes"]}
    if not team_code or not isinstance(team_code, str):
        return jsonify({"error": "team_code is required"}), 400
    if node_id not in valid_ids:
        return jsonify({"error": f"unknown node {node_id}"}), 400

    conn = db.get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO team_compromised_nodes (team_code, node_id, set_by, set_at) "
        "VALUES (?, ?, ?, ?)",
        (team_code, node_id, f"integration:{request.game_name}:{reason}"[:200], time.time()),
    )
    conn.commit()
    conn.close()
    return jsonify({"team_code": team_code, "node_id": node_id, "compromised": True})


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, port=5050)
