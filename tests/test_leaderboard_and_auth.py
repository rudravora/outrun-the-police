import solver


ADMIN_HEADERS = {"X-Admin-Token": "dev-admin-token"}


def route_for_weight(weight_fn):
    graph = solver.load_graph()
    _, route, _ = solver.dijkstra(
        graph,
        graph["hideout"],
        graph["extraction"],
        weight_fn,
        t=0,
        compromised=set(),
    )
    return route


def route_and_edges_for_weight(weight_fn):
    graph = solver.load_graph()
    _, route, edges = solver.dijkstra(
        graph,
        graph["hideout"],
        graph["extraction"],
        weight_fn,
        t=0,
        compromised=set(),
    )
    return route, edges, graph


def test_leaderboard_tracks_best_score_and_orders_teams(client):
    graph = solver.load_graph()
    score_weight = solver.make_score_weight(graph["weights"])

    fastest_route = route_for_weight(solver.time_weight)
    best_score_route, best_score_edges, _ = route_and_edges_for_weight(score_weight)

    fastest = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-A", "route": fastest_route},
    )
    assert fastest.status_code == 200
    assert fastest.get_json()["accepted"] is True

    improved = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-A", "route": best_score_route},
    )
    assert improved.status_code == 200
    assert improved.get_json()["accepted"] is True

    other = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-B", "route": fastest_route},
    )
    assert other.status_code == 200
    assert other.get_json()["accepted"] is True

    leaderboard = client.get(
        "/api/leaderboard",
        headers=ADMIN_HEADERS,
    )

    assert leaderboard.status_code == 200
    rows = leaderboard.get_json()

    assert [row["team_code"] for row in rows] == ["TEAM-A", "TEAM-B"]

    fastest_ok, _, fastest_edges = solver.validate_path(
        graph,
        fastest_route,
        t=0,
        compromised=set(),
    )
    assert fastest_ok is True

    expected_a = solver.path_score(best_score_edges, graph["weights"])
    expected_b = solver.path_score(fastest_edges, graph["weights"])

    assert rows[0]["best_score"] == expected_a
    assert rows[1]["best_score"] == expected_b
    assert expected_a < expected_b


def test_leaderboard_ignores_rejected_submissions(client):
    graph = solver.load_graph()
    score_weight = solver.make_score_weight(graph["weights"])
    route = route_for_weight(score_weight)

    accepted = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-VALID", "route": route},
    )
    assert accepted.status_code == 200

    rejected = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-REJECTED", "route": ["N00", "N59"]},
    )
    assert rejected.status_code == 422

    leaderboard = client.get(
        "/api/leaderboard",
        headers=ADMIN_HEADERS,
    )

    assert leaderboard.status_code == 200
    rows = leaderboard.get_json()

    assert [row["team_code"] for row in rows] == ["TEAM-VALID"]


def test_admin_endpoints_reject_missing_and_invalid_tokens(client):
    for headers in ({}, {"X-Admin-Token": "wrong-token"}):
        response = client.get("/api/leaderboard", headers=headers)

        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

        response = client.get("/api/admin/submissions", headers=headers)

        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}


def test_admin_endpoint_accepts_valid_token(client):
    response = client.get(
        "/api/leaderboard",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    assert response.get_json() == []
