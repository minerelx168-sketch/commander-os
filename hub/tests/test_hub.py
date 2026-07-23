"""Hub tests — 3-round advisory flow, decision log, provider switching."""
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
    assert set(s["decision_stats"]) == {"total", "scored", "saved", "faster", "neutral", "missed"}


def test_consult_runs_three_rounds(client):
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        r = client.post("/api/consult", json={"question": "ควรเปิดสาขาใหม่ไหม"})
    assert r.status_code == 200
    j = r.json()
    for rnd in ("opinions", "cross_exam", "verdicts"):
        assert set(j[rnd]) == {"cmo", "cfo", "coo", "datalyst"}, rnd
        assert all(a["text"] for a in j[rnd].values())
    assert m.call_count == 12  # 4 advisors x 3 rounds
    # cross-exam prompt carries the other advisors' round-1 opinions
    cross_calls = [c for c in m.call_args_list if "วิพากษ์" in c.args[1]]
    assert cross_calls and "ความเห็นของที่ปรึกษาคนอื่น" in cross_calls[0].args[2]
    # persisted + retrievable by id
    assert client.get(f"/api/consults/{j['id']}").json()["question"] == "ควรเปิดสาขาใหม่ไหม"


def test_guardrails_in_prompts(client):
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        client.post("/api/consult", json={"question": "x"})
    opinion_systems = [c.args[1] for c in m.call_args_list if "กฎเหล็ก" in c.args[1]]
    assert len(opinion_systems) == 4
    joined = "\n".join(opinion_systems)
    assert "ห้ามออกความเห็นเรื่องสภาพคล่อง" in joined      # CMO guardrail
    assert "ห้ามออกความเห็นเรื่องกลยุทธ์การตลาด" in joined  # CFO guardrail
    # forced answer structure present in every opinion prompt
    for s in opinion_systems:
        for part in ("มุมมอง/โอกาส", "ความเสี่ยงที่ซ่อนอยู่", "คำแนะนำขั้นเด็ดขาด"):
            assert part in s


def test_decision_log_and_scoring(client):
    r = client.post("/api/decisions", json={"consult_id": 1, "question": "โจทย์", "decision": "ลุย"})
    d = r.json()
    assert d["id"] == 1 and d["verdict"] is None
    r = client.post("/api/decisions/1/score", json={"outcome": "รอด", "verdict": "saved"})
    assert r.json()["verdict"] == "saved"
    j = client.get("/api/decisions").json()
    assert j["stats"]["total"] == 1 and j["stats"]["saved"] == 1
    assert client.post("/api/decisions/1/score", json={"outcome": "", "verdict": "nope"}).status_code == 400
    assert client.post("/api/decisions/99/score", json={"outcome": "", "verdict": "saved"}).status_code == 404


def test_provider_switch(client):
    r = client.put("/api/dept/cfo/provider", json={"provider": "anthropic"})
    assert r.json()["providers"]["cfo"] == "anthropic"
    assert client.put("/api/dept/cfo/provider", json={"provider": "nope"}).status_code == 400
    assert client.put("/api/dept/nope/provider", json={"provider": "mock"}).status_code == 404


def test_index_serves_advisory_ui(client):
    html = client.get("/").text
    for marker in ("view-board", "view-decisions", "view-agents", "Cross-Examination",
                   "Round 1", "Round 3", "askBoard", "recordDecision", "setProvider"):
        assert marker in html, marker
    # automation-era pages are gone
    for stale in ("view-cmo", "runTask", "LLM Learning"):
        assert stale not in html, f"stale automation marker: {stale}"


def test_bad_inputs(client):
    assert client.post("/api/consult", json={"question": "  "}).status_code == 400
    assert client.post("/api/decisions", json={"question": "", "decision": ""}).status_code == 400
    assert client.get("/api/consults/999").status_code == 404
