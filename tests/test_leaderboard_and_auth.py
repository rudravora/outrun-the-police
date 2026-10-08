import solver


ADMIN_HEADERS = {"X-Admin-Token": "dev-admin-token"}

def test_leaderboard_tracks_best_risk_and_orders_teams(client):
    fastest_route = ["N00", "N03", "N07", "N59"]
    low_risk_route = ["N00", "N15", "N30", "N45", "N59"]

    first = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-A", "route": fastest_route},
    )
    assert first.status_code == 200
    assert first.get_json()["accepted"] is True

    improved = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-A", "route": low_risk_route},
    )
    assert improved.status_code == 200
    assert improved.get_json()["accepted"] is True
    assert improved.get_json()["is_new_best"] is True

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

    assert rows[0]["risk"] == 8
    assert rows[0]["time"] == 35
    assert rows[0]["cost"] == 22
    assert rows[0]["has_valid_route"] is True

    assert rows[1]["risk"] == 57
    assert rows[1]["time"] == 3
    assert rows[1]["cost"] == 8
    assert rows[1]["has_valid_route"] is True

def test_leaderboard_marks_rejected_only_teams_as_invalid(client):
    valid_route = ["N00", "N03", "N07", "N59"]

    accepted = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-VALID", "route": valid_route},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["accepted"] is True

    rejected = client.post(
        "/api/submit_route",
        json={"team_code": "TEAM-REJECTED", "route": ["N00", "N59"]},
    )
    assert rejected.status_code == 422
    assert rejected.get_json()["accepted"] is False

    leaderboard = client.get(
        "/api/leaderboard",
        headers=ADMIN_HEADERS,
    )

    assert leaderboard.status_code == 200
    rows = leaderboard.get_json()

    teams = {row["team_code"]: row for row in rows}

    assert "TEAM-VALID" in teams
    assert "TEAM-REJECTED" in teams

    assert teams["TEAM-VALID"]["has_valid_route"] is True
    assert teams["TEAM-REJECTED"]["has_valid_route"] is False

    assert teams["TEAM-VALID"]["risk"] == 57
    assert teams["TEAM-REJECTED"]["risk"] is None

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


def test_team_compromise_accepts_node_id_list(client):
    response = client.post(
        "/api/admin/team_compromise",
        headers=ADMIN_HEADERS,
        json={"team_code": "TEAM01", "node_ids": ["N52", "N11"], "compromised": True},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "team_code": "TEAM01",
        "node_ids": ["N52", "N11"],
        "compromised": True,
    }

    rows = client.get("/api/admin/team_compromised", headers=ADMIN_HEADERS).get_json()
    assert {r["node_id"] for r in rows if r["team_code"] == "TEAM01"} == {"N52", "N11"}


def test_team_compromise_list_rejects_any_bad_id_and_applies_none(client):
    response = client.post(
        "/api/admin/team_compromise",
        headers=ADMIN_HEADERS,
        json={"team_code": "TEAM01", "node_ids": ["N52", "N999"], "compromised": True},
    )

    assert response.status_code == 400
    assert "N999" in response.get_json()["error"]

    rows = client.get("/api/admin/team_compromised", headers=ADMIN_HEADERS).get_json()
    assert rows == []


def test_team_compromise_single_node_id_still_works(client):
    response = client.post(
        "/api/admin/team_compromise",
        headers=ADMIN_HEADERS,
        json={"team_code": "TEAM01", "node_id": "N52", "compromised": True},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "team_code": "TEAM01",
        "node_id": "N52",
        "compromised": True,
    }
