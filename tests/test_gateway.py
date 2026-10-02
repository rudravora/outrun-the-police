import json
import uuid
from urllib.error import HTTPError, URLError

import db
import gateway_client


def test_send_event_builds_correct_gateway_request(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        gateway_client.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    gateway_client.send_event(
        "solved",
        "TEAM-001",
        points=500,
        money_delta=12.5,
        risk=8,
        meta={"example": "value"},
    )

    request = captured["request"]

    assert request.full_url == "http://gateway.test/api/events"
    assert request.get_method() == "POST"
    assert request.get_header("X-game-key") == "test-game-key"
    assert request.get_header("Content-type") == "application/json"
    assert captured["timeout"] == gateway_client.TIMEOUT_SECONDS

    body = json.loads(request.data.decode("utf-8"))

    assert uuid.UUID(body["event_id"])
    assert body["game_id"] == "p2g4"
    assert body["team_id"] == "TEAM-001"
    assert body["type"] == "solved"
    assert body["points"] == 500
    assert body["money_delta"] == 12.5
    assert body["risk"] == 8
    assert body["meta"] == {"example": "value"}
    assert "timestamp" in body


def test_send_event_queues_when_gateway_fails(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    def failed_post(body):
        raise URLError("gateway unavailable")

    monkeypatch.setattr(gateway_client, "_post_event", failed_post)

    gateway_client.send_event(
        "solved",
        "TEAM-QUEUE",
        points=100,
        risk=12,
    )

    pending = db.outbox_pending()

    assert len(pending) == 1

    event = json.loads(pending[0]["body_json"])

    assert event["game_id"] == "p2g4"
    assert event["team_id"] == "TEAM-QUEUE"
    assert event["type"] == "solved"
    assert event["points"] == 100
    assert event["risk"] == 12
    assert pending[0]["attempts"] == 0


def test_send_event_queues_when_gateway_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(gateway_client, "GATEWAY_BASE_URL", "")
    monkeypatch.setattr(gateway_client, "GATEWAY_API_KEY", "")

    def should_not_be_called(body):
        raise AssertionError("HTTP send should not happen when gateway is unconfigured")

    monkeypatch.setattr(gateway_client, "_post_event", should_not_be_called)

    gateway_client.send_event(
        "output_issued",
        "TEAM-NO-GATEWAY",
        meta={"value": "ABCD-1234"},
    )

    pending = db.outbox_pending()

    assert len(pending) == 1

    event = json.loads(pending[0]["body_json"])

    assert event["type"] == "output_issued"
    assert event["team_id"] == "TEAM-NO-GATEWAY"
    assert event["meta"] == {"value": "ABCD-1234"}


def test_get_team_state_returns_gateway_state(monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    def fake_request(method, url, body=None):
        assert method == "GET"
        assert url == "http://gateway.test/api/teams/TEAM-STATE/state"
        assert body is None

        return {
            "team_id": "TEAM-STATE",
            "status": "active",
            "balance": 25.0,
            "unlocked": ["p1g1"],
            "outputs": {},
            "compromised_nodes": ["N15"],
        }

    monkeypatch.setattr(gateway_client, "_request", fake_request)

    state = gateway_client.get_team_state("TEAM-STATE")

    assert state["team_id"] == "TEAM-STATE"
    assert state["balance"] == 25.0
    assert state["compromised_nodes"] == ["N15"]


def test_get_team_state_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    def failed_request(method, url, body=None):
        raise URLError("gateway unavailable")

    monkeypatch.setattr(gateway_client, "_request", failed_request)

    assert gateway_client.get_team_state("TEAM-STATE") is None


def test_duplicate_event_is_treated_as_success(monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    def duplicate_request(method, url, body=None):
        raise HTTPError(
            url,
            409,
            "duplicate event",
            {},
            None,
        )

    monkeypatch.setattr(gateway_client, "_request", duplicate_request)

    body = {
        "event_id": "already-seen",
        "game_id": "p2g4",
        "team_id": "TEAM-DUP",
        "type": "solved",
    }

    assert gateway_client._post_event(body) is True


def test_drain_outbox_delivers_pending_event(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    body = {
        "event_id": "queued-event-1",
        "game_id": "p2g4",
        "team_id": "TEAM-DRAIN",
        "type": "solved",
        "points": 500,
        "money_delta": 0,
        "risk": 8,
        "meta": {},
        "timestamp": "2026-10-02T00:00:00+00:00",
    }

    db.outbox_enqueue(
        body["event_id"],
        json.dumps(body),
    )

    delivered_body = {}

    def successful_post(event):
        delivered_body.update(event)

    monkeypatch.setattr(
        gateway_client,
        "_post_event",
        successful_post,
    )

    delivered, remaining = gateway_client.drain_outbox_once()

    assert delivered == 1
    assert remaining == 0
    assert delivered_body == body
    assert db.outbox_pending() == []

    conn = db.get_conn()
    row = conn.execute(
        "SELECT delivered, attempts, delivered_at FROM gateway_outbox "
        "WHERE event_id = ?",
        (body["event_id"],),
    ).fetchone()
    conn.close()

    assert row["delivered"] == 1
    assert row["attempts"] == 1
    assert row["delivered_at"] is not None

def test_submit_route_uses_gateway_balance(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "get_team_state",
        lambda team_id: {
            "team_id": team_id,
            "balance": 20.0,
            "compromised_nodes": [],
        },
    )

    monkeypatch.setattr(
        gateway_client,
        "send_event",
        lambda *args, **kwargs: None,
    )

    response = client.post(
        "/api/submit_route",
        json={
            "team_code": "TEAM-BUDGET",
            "route": ["N00", "N15", "N30", "N45", "N59"],
        },
    )

    assert response.status_code == 422

    body = response.get_json()

    assert body["accepted"] is False
    assert body["budget"] == 20.0
    assert "budget" in body["reason"].lower()    


def test_drain_outbox_keeps_failed_event_queued(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_BASE_URL",
        "http://gateway.test",
    )
    monkeypatch.setattr(
        gateway_client,
        "GATEWAY_API_KEY",
        "test-game-key",
    )

    body = {
        "event_id": "queued-event-2",
        "game_id": "p2g4",
        "team_id": "TEAM-RETRY",
        "type": "solved",
        "points": 300,
        "money_delta": 0,
        "risk": 14,
        "meta": {},
        "timestamp": "2026-10-02T00:00:00+00:00",
    }

    db.outbox_enqueue(
        body["event_id"],
        json.dumps(body),
    )

    def failed_post(event):
        raise URLError("gateway still down")

    monkeypatch.setattr(
        gateway_client,
        "_post_event",
        failed_post,
    )

    delivered, remaining = gateway_client.drain_outbox_once()

    assert delivered == 0
    assert remaining == 1

    pending = db.outbox_pending()

    assert len(pending) == 1
    assert pending[0]["event_id"] == body["event_id"]
    assert pending[0]["attempts"] == 1

def test_submit_route_uses_gateway_compromised_nodes(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "get_team_state",
        lambda team_id: {
            "team_id": team_id,
            "balance": 100.0,
            "compromised_nodes": ["N15"],
        },
    )

    monkeypatch.setattr(
        gateway_client,
        "send_event",
        lambda *args, **kwargs: None,
    )

    response = client.post(
        "/api/submit_route",
        json={
            "team_code": "TEAM-COMPROMISED",
            "route": ["N00", "N15", "N30", "N45", "N59"],
        },
    )

    assert response.status_code == 422

    body = response.get_json()

    assert body["accepted"] is False
    assert "N15" in body["reason"]
    assert "compromised" in body["reason"].lower()

def test_accepted_submission_sends_gateway_events(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "get_team_state",
        lambda team_id: None,
    )

    events = []

    def fake_send_event(
        event_type,
        team_id,
        points=0,
        money_delta=0,
        risk=None,
        meta=None,
    ):
        events.append(
            {
                "event_type": event_type,
                "team_id": team_id,
                "points": points,
                "money_delta": money_delta,
                "risk": risk,
                "meta": meta,
            }
        )

    monkeypatch.setattr(
        gateway_client,
        "send_event",
        fake_send_event,
    )

    response = client.post(
        "/api/submit_route",
        json={
            "team_code": "TEAM-EVENTS",
            "route": ["N00", "N15", "N30", "N45", "N59"],
        },
    )

    assert response.status_code == 200

    body = response.get_json()

    assert body["accepted"] is True
    assert body["is_new_best"] is True

    assert [event["event_type"] for event in events] == [
        "solved",
        "output_issued",
    ]

    solved = events[0]

    assert solved["team_id"] == "TEAM-EVENTS"
    assert solved["risk"] == body["breakdown"]["risk"]

    output = events[1]

    assert output["team_id"] == "TEAM-EVENTS"
    assert output["meta"]["value"] == body["route_code"]

    assert len(body["route_code"]) == 9
    assert body["route_code"][4] == "-"

def test_rejected_submission_does_not_send_gateway_event(client, monkeypatch):
    monkeypatch.setattr(
        gateway_client,
        "get_team_state",
        lambda team_id: None,
    )

    events = []

    monkeypatch.setattr(
        gateway_client,
        "send_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    response = client.post(
        "/api/submit_route",
        json={
            "team_code": "TEAM-REJECTED-EVENT",
            "route": ["N00", "N59"],
        },
    )

    assert response.status_code == 422

    body = response.get_json()

    assert body["accepted"] is False
    assert events == []