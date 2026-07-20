"""meta-ads-agent integration tests: normalization + decision forwarding."""
from unittest.mock import patch

from app.services import meta_ads_client as mac


def _fake_response(json_data, status=200):
    class R:
        status_code = status

        def json(self):
            return json_data

        def raise_for_status(self):
            pass

    return R()


def test_recommendation_normalization_live_shape(db, monkeypatch):
    """Real meta-ads-agent shape -> CMO node shape."""
    monkeypatch.setattr(mac.get_settings(), "meta_agent_mock", False)
    raw = [{
        "id": 7, "level": "campaign", "entity_meta_id": "123", "entity_name": "Camp X",
        "action_type": "PAUSE_AD", "current_value": None, "proposed_value": None,
        "final_value": None, "justification": "CTR ต่ำมาก", "metrics_context": None,
        "guardrail_flags": None, "status": "PENDING", "created_at": "2026-07-20T00:00:00",
    }]
    with patch.object(mac.httpx, "get", return_value=_fake_response(raw)):
        recs = mac.get_recommendations()
    monkeypatch.setattr(mac.get_settings(), "meta_agent_mock", True)

    assert recs == [{
        "id": 7, "action": "PAUSE_AD", "target": "Camp X",
        "params": {"current": None, "proposed": None},
        "reason": "CTR ต่ำมาก", "status": "PENDING",
    }]


def test_decide_forwards_to_meta_agent(monkeypatch):
    monkeypatch.setattr(mac.get_settings(), "meta_agent_mock", False)
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return _fake_response({"id": 7, "status": "APPROVED"})

    with patch.object(mac.httpx, "post", side_effect=fake_post):
        out = mac.decide_recommendation(7, "approve")
    monkeypatch.setattr(mac.get_settings(), "meta_agent_mock", True)

    assert out["status"] == "APPROVED"
    assert calls[0].endswith("/api/recommendations/7/approve")


def test_approval_flow_executes_recommendation(client, db):
    """Full loop: approve -> cmo forwards decision -> audit trail records it."""
    from app.models import AuditLog

    r = client.post("/api/command", json={"text": "วิเคราะห์แคมเปญ"})
    task_id = r.json()["task_id"]
    approval_id = client.get("/api/approvals").json()[0]["id"]
    client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"})

    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "done"
    events = [a.event for a in db.query(AuditLog).all()]
    assert "recommendation_approved" in events
