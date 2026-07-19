"""API + Telegram mock tests."""
import time


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["llm_mock"] is True


def test_command_to_approval_to_report_flow(client, db):
    from app.services.telegram_bot import MOCK_OUTBOX

    MOCK_OUTBOX.clear()

    # 1. send command
    r = client.post("/api/command", json={"text": "วิเคราะห์แคมเปญวันนี้"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    # background task runs synchronously in TestClient; task should now wait approval
    r = client.get(f"/api/tasks/{task_id}")
    assert r.json()["status"] == "waiting_approval"

    # telegram approval card was "sent"
    assert any("อนุมัติ" in str(m) for m in MOCK_OUTBOX)

    # 2. pending approval visible
    r = client.get("/api/approvals")
    approvals = r.json()
    assert len(approvals) == 1
    approval_id = approvals[0]["id"]

    # 3. approve -> graph resumes -> task done with report
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    r = client.get(f"/api/tasks/{task_id}")
    assert r.json()["status"] == "done"
    assert r.json()["result"]["report"]

    # final report delivered via telegram
    assert any("สรุป" in str(m) for m in MOCK_OUTBOX)


def test_daily_report(client, db):
    r = client.get("/api/report/daily")
    assert r.status_code == 200
    assert "Commander OS" in r.json()["report"]
