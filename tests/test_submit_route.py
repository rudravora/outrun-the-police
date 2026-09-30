import solver


def test_valid_reference_route_is_accepted_and_score_matches_solver(client):
    graph = solver.load_graph()
    _, expected_route, expected_edges = solver.dijkstra(
        graph,
        graph["hideout"],
        graph["extraction"],
        solver.time_weight,
        t=0,
        compromised=set(),
    )

    expected_score = solver.path_score(expected_edges, graph["weights"])

    response = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-TEST", "route": expected_route},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["accepted"] is True
    assert body["reason"] == "ok"
    assert body["route"] == expected_route
    assert body["breakdown"]["score"] == expected_score
    assert body["is_new_best"] is True
