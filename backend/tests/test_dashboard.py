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
    # Sureflow-style panels
    ops = snap["ops"]
    for k in ("integrity_pct", "agent_calls", "messages", "tokens_in", "tokens_out", "errors"):
        assert k in ops
    h = snap["health"]
    for k in ("cpu_pct", "ram_pct", "disk_pct", "ram_total_mb", "disk_total_gb"):
        assert k in h
    assert "directive" in snap and "context" in snap


def test_snapshot_directive_and_context(client, db):
    from app.models import Agent, AuditLog, Task

    db.add_all([
        Agent(name="ceo", role="CEO", model="mock"),
        Task(created_by="owner", assigned_to="ceo", title="ทำรีลส์เดโม", status="in_progress"),
        AuditLog(agent="ceo", event="เริ่มวางแผนรีลส์"),
    ])
    db.commit()

    snap = client.get("/api/snapshot").json()
    assert snap["directive"]["title"] == "ทำรีลส์เดโม"
    assert snap["context"]["agent"] == "ceo"
    assert snap["context"]["open_tasks"] == 1
    assert snap["context"]["last_status"] == "เริ่มวางแผนรีลส์"


def test_dashboard_page(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Commander OS" in r.text
    assert "System Health" in r.text
    # Sureflow-style chat-first UI: Command Center / Projects / Departments
    assert "view-chat" in r.text
    assert "view-projects" in r.text
    assert "view-departments" in r.text
    assert "agent-strip" in r.text
    assert "chat-feed" in r.text
    assert "Command Center" in r.text


def test_projects_api(client, db):
    from app.models import AuditLog, Task

    db.add_all([
        Task(created_by="owner", assigned_to="ceo", title="ภารกิจทดสอบ",
             status="done", result={"report": "รายงาน", "brief": "x.md"}),
    ])
    db.commit()
    t = db.query(Task).first()
    db.add_all([
        AuditLog(agent="cmo", task_id=t.id, event="analysis_done", detail={}),
        AuditLog(agent="ceo", task_id=t.id, event="boardroom_decision",
                 detail={"message": "มติ: ok"}),
    ])
    db.commit()

    r = client.get("/api/projects")
    assert r.status_code == 200
    p = r.json()["projects"][0]
    assert p["title"] == "ภารกิจทดสอบ"
    assert p["progress"] == 100
    assert "cmo" in p["departments"]
    assert p["boardroom"][0]["speaker"] == "ceo"
    assert p["boardroom"][0]["decision"] is True
    assert p["report"] == "รายงาน" and p["brief"] == "x.md"


def test_kill_switch_blocks_commands(client, db):
    r = client.post("/api/kill-switch", params={"engage": True})
    assert r.json()["engaged"] is True

    r = client.post("/api/command", json={"text": "ทดสอบ"})
    assert r.status_code == 503

    r = client.post("/api/kill-switch", params={"engage": False})
    assert r.json()["engaged"] is False

    r = client.post("/api/command", json={"text": "ทดสอบ"})
    assert r.status_code == 200
