"""Hub tests — consult tree, dept tasks + learning, provider switching."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    import app.store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "hub_store.json")
    from app.main import app
    return TestClient(app)


def _fake_chat(provider, system, user):
    return {"text": f"[{provider}] คำตอบทดสอบ", "provider": provider, "model": "m", "ok": True}


def test_state_shape(client):
    s = client.get("/api/state").json()
    assert {d["key"] for d in s["depts"]} == {"cmo", "cfo", "coo", "datalyst"}
    assert {p["key"] for p in s["providers"]} >= {"anthropic", "gemini", "manus", "mock"}
    for d in s["depts"]:
        assert {"name", "icon", "role", "provider", "provider_ready", "online"} <= set(d)


def test_consult_returns_all_four_answers(client):
    with patch("app.llm.chat", side_effect=_fake_chat):
        r = client.post("/api/consult", json={"question": "ควรเปิดสาขาใหม่ไหม"})
    assert r.status_code == 200
    j = r.json()
    assert j["question"] == "ควรเปิดสาขาใหม่ไหม"
    assert set(j["answers"]) == {"cmo", "cfo", "coo", "datalyst"}
    assert all(a["text"] for a in j["answers"].values())
    # history persisted
    h = client.get("/api/consults").json()["consults"]
    assert h[0]["question"] == "ควรเปิดสาขาใหม่ไหม"


def test_dept_task_logs_and_learns(client):
    with patch("app.llm.chat", side_effect=_fake_chat), \
         patch("app.depts._svc_context", return_value="(no data)"):
        r = client.post("/api/dept/cmo/task", json={"command": "ทำแผนโปรโมชั่น"})
    assert r.status_code == 200
    t = r.json()
    assert t["dept"] == "cmo" and t["command"] == "ทำแผนโปรโมชั่น" and t["id"] == 1
    j = client.get("/api/dept/cmo/tasks").json()
    assert j["tasks"][0]["command"] == "ทำแผนโปรโมชั่น"
    assert len(j["lessons"]) == 1  # LLM learning captured a lesson


def test_provider_switch(client):
    r = client.put("/api/dept/cfo/provider", json={"provider": "anthropic"})
    assert r.json()["providers"]["cfo"] == "anthropic"
    s = client.get("/api/state").json()
    cfo = next(d for d in s["depts"] if d["key"] == "cfo")
    assert cfo["provider"] == "anthropic"
    assert client.put("/api/dept/cfo/provider", json={"provider": "nope"}).status_code == 400
    assert client.put("/api/dept/nope/provider", json={"provider": "mock"}).status_code == 404


def test_index_serves_ui(client):
    html = client.get("/").text
    for marker in ("Command Overall", "view-overall", "view-cmo", "view-cfo",
                   "view-coo", "view-datalyst", "view-agents", "tree-branches",
                   "askBoard", "setProvider"):
        assert marker in html, marker


def test_bad_inputs(client):
    assert client.post("/api/consult", json={"question": "  "}).status_code == 400
    assert client.post("/api/dept/cmo/task", json={"command": ""}).status_code == 400
    assert client.post("/api/dept/nope/task", json={"command": "x"}).status_code == 404
