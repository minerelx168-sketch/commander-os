"""Deliverable brief generation + API tests."""
from app.services import deliverable


def _fake_state():
    return {
        "department_results": {"cmo": "ads วิเคราะห์แล้ว", "cfo": "งบยังโอเค"},
        "boardroom_log": [
            {"speaker": "cmo", "message": "เห็นด้วยเรื่องคุมงบ"},
            {"speaker": "ceo", "message": "มติ: ปรับงบ 10%"},
        ],
        "ceo_decision": "มติ: ปรับงบ 10%",
        "final_report": "สรุป: ทุกอย่างเรียบร้อย",
    }


def test_build_brief_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(deliverable, "DELIVERABLES_DIR", tmp_path)
    fname = deliverable.build_brief(42, "วิเคราะห์แคมเปญ", _fake_state())
    assert fname.endswith(".md") and "task42" in fname
    text = (tmp_path / fname).read_text(encoding="utf-8")
    assert "Executive Brief #42" in text
    assert "CMO — การตลาด" in text and "ads วิเคราะห์แล้ว" in text
    assert "บันทึกการประชุมบอร์ด" in text and "มติ: ปรับงบ 10%" in text
    assert "รายงานสรุปถึงเจ้าของ" in text


def test_deliverables_api_list_and_read(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deliverable, "DELIVERABLES_DIR", tmp_path)
    fname = deliverable.build_brief(7, "ทดสอบ", _fake_state())

    r = client.get("/api/deliverables")
    assert r.status_code == 200
    briefs = r.json()["briefs"]
    assert briefs[0]["filename"] == fname

    r = client.get(f"/api/deliverables/{fname}")
    assert r.status_code == 200
    assert "Executive Brief #7" in r.text


def test_deliverables_api_blocks_traversal(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deliverable, "DELIVERABLES_DIR", tmp_path)
    assert client.get("/api/deliverables/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/deliverables/nope.md").status_code == 404


def test_full_command_flow_produces_brief(client, db, tmp_path, monkeypatch):
    """MOCK end-to-end: command → done task carries a brief filename on disk."""
    monkeypatch.setattr(deliverable, "DELIVERABLES_DIR", tmp_path)

    r = client.post("/api/command", json={"text": "สวัสดี รายงานสถานะหน่อย"})
    task_id = r.json()["task_id"]
    t = client.get(f"/api/tasks/{task_id}").json()
    if t["status"] == "waiting_approval":  # mock plan routes to CMO → approval
        ap = client.get("/api/approvals").json()[0]
        client.post(f"/api/approvals/{ap['id']}/decide",
                    json={"decision": "approve", "decided_by": "owner:test"})
        t = client.get(f"/api/tasks/{task_id}").json()
    assert t["status"] == "done"
    assert t["result"]["brief"] and (tmp_path / t["result"]["brief"]).is_file()
