import solver


def test_nonexistent_path_is_rejected(client):
    response = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-BAD-PATH", "route": ["N00", "N59"]},
    )

    assert response.status_code == 422
    body = response.get_json()
    assert body["accepted"] is False
    assert body["reason"] == "no edge from N00 to N59"


def test_closed_edge_is_rejected(client):
    # E82 is N00 -> N29 and is only open from t=9 through t=63.
    # The test DB starts at event time t=0.
    route = ["N00", "N29"] + [f"N{i:02d}" for i in range(30, 60)]

    response = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-CLOSED", "route": route},
    )

    assert response.status_code == 422
    body = response.get_json()
    assert body["accepted"] is False
    assert body["reason"] == "edge N00->N29 not open at t=0.0"


def test_compromised_node_is_rejected(client):
    # First submit the known-valid reference route.
    graph = solver.load_graph()
    _, route, _ = solver.dijkstra(
        graph,
        graph["hideout"],
        graph["extraction"],
        solver.time_weight,
        t=0,
        compromised=set(),
    )

    node_to_compromise = route[1]

    compromise = client.post(
        "/api/admin/compromise",
        json={"node_id": node_to_compromise, "compromised": True},
        headers={"X-Admin-Token": "dev-admin-token"},
    )
    assert compromise.status_code == 200

    response = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-COMPROMISED", "route": route},
    )

    assert response.status_code == 422
    body = response.get_json()
    assert body["accepted"] is False
    assert body["reason"] == f"{node_to_compromise} is compromised"
