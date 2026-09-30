import solver


ADMIN_HEADERS = {"X-Admin-Token": "dev-admin-token"}


def reference_route():
    graph = solver.load_graph()
    _, route, _ = solver.dijkstra(
        graph,
        graph["hideout"],
        graph["extraction"],
        solver.time_weight,
        t=0,
        compromised=set(),
    )
    return route


def test_grandfathered_submission_remains_accepted_after_compromise(client):
    route = reference_route()

    first = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-GRAND", "route": route},
    )

    assert first.status_code == 200
    assert first.get_json()["accepted"] is True

    node_to_compromise = route[1]

    compromise = client.post(
        "/api/admin/compromise",
        json={"node_id": node_to_compromise, "compromised": True},
        headers=ADMIN_HEADERS,
    )

    assert compromise.status_code == 200
    assert compromise.get_json()["compromised"] is True

    second = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-GRAND", "route": route},
    )

    assert second.status_code == 422
    second_body = second.get_json()
    assert second_body["accepted"] is False
    assert second_body["reason"] == f"{node_to_compromise} is compromised"

    submissions = client.get(
        "/api/admin/submissions",
        headers=ADMIN_HEADERS,
    )

    assert submissions.status_code == 200
    rows = submissions.get_json()

    team_rows = [row for row in rows if row["team_code"] == "TEAM-GRAND"]
    assert len(team_rows) == 2

    accepted_rows = [row for row in team_rows if row["valid"] == 1]
    rejected_rows = [row for row in team_rows if row["valid"] == 0]

    assert len(accepted_rows) == 1
    assert len(rejected_rows) == 1
    assert rejected_rows[0]["reason"] == f"{node_to_compromise} is compromised"


def test_event_clock_changes_edge_validity(client):
    # N03 -> N22 is open at t=10 but closed by t=40.
    route = [
        "N00", "N03", "N22", "N23", "N24", "N25",
        "N26", "N27", "N28", "N29", "N30", "N45", "N59",
    ]

    set_10 = client.post(
        "/api/admin/clock",
        json={"action": "set", "t": 10},
        headers=ADMIN_HEADERS,
    )
    assert set_10.status_code == 200
    assert set_10.get_json()["event_time"] == 10.0

    at_10 = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-CLOCK", "route": route},
    )

    assert at_10.status_code == 200
    body_10 = at_10.get_json()
    assert body_10["accepted"] is True
    assert body_10["event_time"] == 10.0

    set_40 = client.post(
        "/api/admin/clock",
        json={"action": "set", "t": 40},
        headers=ADMIN_HEADERS,
    )
    assert set_40.status_code == 200
    assert set_40.get_json()["event_time"] == 40.0

    at_40 = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-CLOCK", "route": route},
    )

    assert at_40.status_code == 422
    body_40 = at_40.get_json()
    assert body_40["accepted"] is False
    assert body_40["reason"] == "edge N03->N22 not open at t=40.0"
    assert body_40["event_time"] == 40.0
