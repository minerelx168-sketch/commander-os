"""Dashboard API tests."""


def test_snapshot_shape(client, db):
    from app.models import Agent

    db.add_all([
        Agent(name="ceo", role="CEO", model="mock"),
        Agent(name="cmo", role="CMO", model="mock"),
    ])
    db.commit()

    r = client.get("/api/snapshot")
    assert r.status_code == 200
    snap = r.json()
    assert {a["name"] for a in snap["agents"]} == {"ceo", "cmo"}
    assert snap["agents"][0]["status"] in ("IDLE", "WORKING", "WAITING")
    assert "kpi" in snap and "approvals" in snap and "activity" in snap


def test_dashboard_page(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "COMMANDER OS" in r.text


def test_kill_switch_blocks_commands(client, db):
    r = client.post("/api/kill-switch", params={"engage": True})
    assert r.json()["engaged"] is True

    r = client.post("/api/command", json={"text": "ทดสอบ"})
    assert r.status_code == 503

    r = client.post("/api/kill-switch", params={"engage": False})
    assert r.json()["engaged"] is False

    r = client.post("/api/command", json={"text": "ทดสอบ"})
    assert r.status_code == 200
