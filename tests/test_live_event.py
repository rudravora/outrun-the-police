from app import ADMIN_TOKEN
import gateway_client


ADMIN_HEADERS = {
    "X-Admin-Token": ADMIN_TOKEN,
}

ROUTE_A = [
    "N00",
    "N03",
    "N22",
    "N23",
    "N24",
    "N25",
    "N26",
    "N27",
    "N28",
    "N29",
    "N30",
    "N45",
    "N59",
]

ROUTE_B = [
    "N00",
    "N01",
    "N02",
    "N03",
    "N37",
    "N42",
    "N45",
    "N46",
    "N47",
    "N59",
]


def set_clock(client, event_time):
    response = client.post(
        "/api/admin/clock",
        json={
            "action": "set",
            "t": event_time,
        },
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200

    body = response.get_json()
    assert body["event_time"] == float(event_time)

    return body


def set_compromised(client, node_id, compromised):
    response = client.post(
        "/api/admin/compromise",
        json={
            "node_id": node_id,
            "compromised": compromised,
        },
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200

    body = response.get_json()
    assert body["node_id"] == node_id
    assert body["compromised"] is compromised

    return body


def submit(client, team_code, route):
    return client.post(
        "/api/submit_route",
        json={
            "team_code": team_code,
            "route": route,
        },
    )


def test_live_event_walkthrough(client, monkeypatch):
    # Keep this test entirely local.
    # The real gateway is not configured yet, and the live values are
    # deliberately not hard-coded into the test suite.
    monkeypatch.setattr(
        gateway_client,
        "get_team_state",
        lambda team_id: None,
    )
    monkeypatch.setattr(
        gateway_client,
        "send_event",
        lambda *args, **kwargs: None,
    )

    team_code = "LIVE-TEAM"

    # ---------------------------------------------------------------
    # T+0:00 — Event starts.
    # ---------------------------------------------------------------
    set_clock(client, 0)

    # The graph should report the same event time to a team.
    response = client.get("/api/graph")
    assert response.status_code == 200

    graph = response.get_json()
    assert graph["event_time"] == 0.0

    # Nothing should be compromised at event start.
    assert "N22" not in graph["compromised_nodes"]

    # ---------------------------------------------------------------
    # T+0:12 — Team submits Route A.
    # ---------------------------------------------------------------
    set_clock(client, 12)

    response = submit(client, team_code, ROUTE_A)

    assert response.status_code == 200

    body = response.get_json()

    assert body["accepted"] is True
    assert body["is_new_best"] is True

    assert body["breakdown"]["time"] == 72
    assert body["breakdown"]["risk"] == 46
    assert body["breakdown"]["cost"] == 61

    # Route A becomes the team's current best.
    assert body["route"] == ROUTE_A

    # ---------------------------------------------------------------
    # T+0:25 — Organizer compromises N22.
    # ---------------------------------------------------------------
    set_clock(client, 25)
    set_compromised(client, "N22", True)

    # Confirm the graph exposes the changed live state.
    response = client.get("/api/graph")
    assert response.status_code == 200

    graph = response.get_json()

    assert graph["event_time"] == 25.0
    assert "N22" in graph["compromised_nodes"]

    node_22 = next(
        node for node in graph["nodes"]
        if node["id"] == "N22"
    )

    assert node_22["compromised"] is True

    # ---------------------------------------------------------------
    # T+0:31 — Team resubmits Route A.
    # It was valid before the compromise, but is now rejected.
    # ---------------------------------------------------------------
    set_clock(client, 31)

    response = submit(client, team_code, ROUTE_A)

    assert response.status_code == 422

    body = response.get_json()

    assert body["accepted"] is False
    assert body["reason"] == "N22 is compromised"

    # The original accepted submission must still exist.
    response = client.get(
        f"/api/team/{team_code}/history"
    )

    assert response.status_code == 200

    history = response.get_json()

    assert len(history) == 2
    assert history[0]["valid"] == 0
    assert history[0]["reason"] == "N22 is compromised"
    assert history[1]["valid"] == 1

    # ---------------------------------------------------------------
    # T+0:40 — Team replans and submits Route B.
    # ---------------------------------------------------------------
    set_clock(client, 40)

    response = submit(client, team_code, ROUTE_B)

    assert response.status_code == 200

    body = response.get_json()

    assert body["accepted"] is True
    assert body["is_new_best"] is True

    assert body["breakdown"]["time"] == 75
    assert body["breakdown"]["risk"] == 29
    assert body["breakdown"]["cost"] == 59

    # New route is slower but lower-risk.
    assert body["breakdown"]["time"] > 72
    assert body["breakdown"]["risk"] < 46

    # ---------------------------------------------------------------
    # T+0:55 — Submission window reaches its final point.
    #
    # The current backend does not have a separate "close submissions"
    # API, so we verify the final state that the organizer would hand off:
    # the team's best valid route is Route B.
    # ---------------------------------------------------------------
    set_clock(client, 55)

    response = client.get(
        "/api/leaderboard",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200

    leaderboard = response.get_json()

    assert leaderboard == [
        {
            "team_code": team_code,
            "risk": 29,
            "time": 75,
            "cost": 59,
            "budget": 100.0,
            "deadline": 120,
            "has_valid_route": True,
        }
    ]

    # ---------------------------------------------------------------
    # Handoff — final best route is available through the admin export.
    # ---------------------------------------------------------------
    response = client.get(
        "/api/admin/export",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200

    export = response.get_json()

    assert len(export) == 1

    result = export[0]

    assert result["team_code"] == team_code
    assert result["route"] == ROUTE_B