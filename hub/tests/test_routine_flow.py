"""Correcting a routine's reasoning at the node it went wrong.

The flow the CEO works in: input → thinking → decision → output, with ✏️ on
any node. A correction is not a note filed beside the report — it is handed to
the next run as a closed road, and that run must answer for it.
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TRACE = {
    "understanding": "สรุปยอดขายรายสัปดาห์แยกตามช่องทาง",
    "steps": [
        {"step": "ดึงยอดขาย 4 สัปดาห์", "why": "ต้องมีฐานเทียบ", "found": "โต 8%"},
        {"step": "แยกยอดตามช่องทาง", "why": "งบผูกกับช่องทาง", "found": "ออนไลน์ 62%"},
    ],
    "assumptions": ["ยอดสาขาใหม่ใกล้เคียงสาขาเดิม"],
    "evidence_used": ["เอกสาร: sales-july.txt"],
    "unknowns": ["ยอดคืนสินค้ายังไม่เข้าระบบ"],
    "answer": "ยอดขายสัปดาห์นี้ 120,000 บาท (+8%)",
    "next_actions": [{"action": "เช็คยอด POS สาขา 3", "owner": "COO", "due": "ศุกร์"}],
    "confidence": 72,
    "self_check": "ถ้าผิด จะผิดที่สมมติฐานยอดสาขาใหม่",
    "changed_from_last": "",
    "fix_responses": [],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    import app.store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "hub_store.json")
    import app.sources as sources
    monkeypatch.setattr(sources, "_FILE", tmp_path / "sources.json")
    import app.docs as docs
    monkeypatch.setattr(docs, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(docs, "_META", tmp_path / "_meta.json")
    import app.routines as routines
    routines._LIVE.clear()
    from app.main import app
    return TestClient(app)


def _routine(client, seats=("cfo",)):
    return client.post("/api/routines", json={
        "task": "สรุปยอดขายรายสัปดาห์", "frequency": "daily",
        "time": "09:00", "seats": list(seats)}).json()


def _run(client, rid, trace=None, capture=None):
    """Run with a canned JSON trace; `capture` collects the prompts sent."""
    payload = json.dumps(trace or TRACE, ensure_ascii=False)

    def reply(provider, system, user, **kw):
        if capture is not None:
            capture.append(user)
        return {"text": payload, "provider": provider, "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=reply), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [1]}):
        return client.post(f"/api/routines/{rid}/run").json()


# ── the flow is visible ──

def test_a_run_carries_the_whole_path_not_just_the_answer(client):
    r = _routine(client)
    _run(client, r["id"])
    j = client.get(f"/api/pipeline/routines/{r['id']}").json()
    t = j["runs"][0]["results"]["cfo"]["trace"]
    assert t["understanding"] and t["answer"]
    assert len(t["steps"]) == 2 and t["steps"][0]["why"]
    assert t["assumptions"] and t["evidence_used"] and t["unknowns"]
    assert t["confidence"] == 72 and t["self_check"]


def test_the_report_the_ceo_reads_is_the_deliverable_not_the_json(client):
    """Telegram must carry the answer, never the scaffolding around it."""
    r = _routine(client)
    sent = {}

    def capture_send(text, **kw):
        sent["text"] = text
        return {"ok": True, "sent": 1, "message_ids": [1]}

    with patch("app.llm.chat", return_value={"text": json.dumps(TRACE, ensure_ascii=False),
                                             "provider": "p", "model": "m", "ok": True}), \
         patch("app.telegram.send", side_effect=capture_send):
        client.post(f"/api/routines/{r['id']}/run")
    assert TRACE["answer"] in sent["text"]
    assert "understanding" not in sent["text"], "raw JSON leaked into Telegram"
    assert "confidence" not in sent["text"]


def test_prose_still_reports_even_though_it_cannot_be_corrected(client):
    """Losing the report to a formatting slip is worse than losing the flow."""
    r = _routine(client)
    with patch("app.llm.chat", return_value={"text": "ยอดขายโต 8% ครับ", "provider": "p",
                                             "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [1]}):
        client.post(f"/api/routines/{r['id']}/run")
    run = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]
    assert run["results"]["cfo"]["trace"] is None
    assert "8%" in run["results"]["cfo"]["text"]
    assert run["health"] == "done", "a prose report is still a report"


def test_every_node_of_the_path_is_addressable(client):
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    for node in ("understanding", "steps[0]", "steps[1]", "assumptions[0]",
                 "evidence_used[0]", "unknowns[0]", "next_actions[0]",
                 "self_check", "answer"):
        res = client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
            "run": run_id, "dept": "cfo", "node": node,
            "should": f"ควรเป็นอย่างอื่นที่ {node}", "rerun": False})
        assert res.status_code == 200, (node, res.text[:200])


def test_a_node_never_written_is_refused_not_invented(client):
    """Quoting a model reasoning it never did is worse than declining."""
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    res = client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": run_id, "dept": "cfo", "node": "steps[9]",
        "should": "x", "rerun": False})
    assert res.status_code == 400 and "ไม่พบจุด" in res.json()["detail"]


# ── a correction changes the next run ──

def test_the_correction_reaches_the_next_run_quoted_at_its_node(client):
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": run_id, "dept": "cfo", "node": "steps[1]",
        "should": "ต้องแยกยอดรายสาขาด้วย ไม่ใช่แค่ช่องทาง", "rerun": False})

    seen = []
    _run(client, r["id"], capture=seen)
    prompt = seen[0]
    assert "steps[1]" in prompt
    assert "ต้องแยกยอดรายสาขาด้วย" in prompt
    assert "แยกยอดตามช่องทาง" in prompt, "the rejected reasoning was not quoted back"
    assert "ต้องทำตามให้ครบ" in prompt, "the correction was not made binding"


def test_what_the_ceo_rejected_survives_later_runs(client):
    """`was` is captured at correction time: indices shift, the record must not."""
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": run_id, "dept": "cfo", "node": "steps[1]",
        "should": "แยกรายสาขา", "rerun": False})

    shifted = {**TRACE, "steps": [{"step": "ขั้นใหม่", "why": "", "found": ""}]}
    _run(client, r["id"], trace=shifted)

    fixes = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][-1] \
        ["results"]["cfo"]["fixes"]
    assert fixes and "แยกยอดตามช่องทาง" in fixes[0]["was"]


def test_a_correction_is_not_replayed_forever(client):
    """Once a run has received it, it is answered — otherwise every future run
    is told to fix something that was already addressed."""
    from app import store
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": run_id, "dept": "cfo", "node": "answer",
        "should": "ใส่ตัวเลขรายสาขาด้วย", "rerun": False})
    assert len(store.open_routine_corrections(r["id"])) == 1

    seen = []
    _run(client, r["id"], capture=seen)
    assert "ใส่ตัวเลขรายสาขาด้วย" in seen[0]
    assert store.open_routine_corrections(r["id"]) == []

    seen2 = []
    _run(client, r["id"], capture=seen2)
    assert "ใส่ตัวเลขรายสาขาด้วย" not in seen2[0], "correction replayed after being answered"


def test_a_correction_only_reaches_the_seat_it_was_aimed_at(client):
    r = _routine(client, seats=("cfo", "coo"))
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": run_id, "dept": "cfo", "node": "answer",
        "should": "เฉพาะ CFO เท่านั้น", "rerun": False})

    prompts = {}

    def reply(provider, system, user, **kw):
        prompts["cfo" if "CFO" in system else "coo"] = user
        return {"text": json.dumps(TRACE, ensure_ascii=False), "provider": provider,
                "model": "m", "ok": True}

    with patch("app.llm.chat", side_effect=reply), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [1]}):
        client.post(f"/api/routines/{r['id']}/run")

    assert "เฉพาะ CFO เท่านั้น" in prompts["cfo"]
    assert "เฉพาะ CFO เท่านั้น" not in prompts["coo"]


def test_rerun_true_produces_the_corrected_round_immediately(client):
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    with patch("app.llm.chat", return_value={"text": json.dumps(
                   {**TRACE, "changed_from_last": "แยกรายสาขาแล้ว"}, ensure_ascii=False),
               "provider": "p", "model": "m", "ok": True}), \
         patch("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [2]}):
        out = client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
            "run": run_id, "dept": "cfo", "node": "answer",
            "should": "แยกรายสาขา", "rerun": True}).json()
    assert out["run"] is not None
    j = client.get(f"/api/pipeline/routines/{r['id']}").json()
    assert len(j["runs"]) == 2
    assert j["runs"][0]["results"]["cfo"]["trace"]["changed_from_last"]


def test_a_correction_can_be_withdrawn(client):
    r = _routine(client)
    _run(client, r["id"])
    run_id = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    fix = client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": run_id, "dept": "cfo", "node": "answer",
        "should": "เปลี่ยนใจ", "rerun": False}).json()["fix"]
    assert client.delete(f"/api/pipeline/fixes/{fix['id']}").status_code == 200
    assert client.get(f"/api/pipeline/routines/{r['id']}").json()["open_fixes"] == []
    assert client.delete(f"/api/pipeline/fixes/{fix['id']}").status_code == 404


def test_the_correction_shows_on_the_run_it_was_aimed_at(client):
    """It lives on the run that was wrong — that is where the CEO is looking."""
    r = _routine(client)
    _run(client, r["id"])
    first = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"][0]["id"]
    client.post(f"/api/pipeline/routines/{r['id']}/fix", json={
        "run": first, "dept": "cfo", "node": "steps[0]",
        "should": "ใช้ 8 สัปดาห์", "rerun": False})
    _run(client, r["id"])

    runs = client.get(f"/api/pipeline/routines/{r['id']}").json()["runs"]
    newest, corrected = runs[0], runs[1]
    assert corrected["id"] == first
    assert corrected["results"]["cfo"]["fixes"][0]["node"] == "steps[0]"
    assert newest["results"]["cfo"]["fixes"] == [], "the fix belongs to the wrong run"


def test_the_seat_prompt_avoids_the_phrasing_that_makes_claude_refuse(client):
    """Measured on claude-fable-5: a system line telling the seat that the CEO
    "will see your chain of thought / เส้นทางการคิด" returns stop_reason=refusal
    5/5, while the same prompt without it succeeds 5/5. The schema asks for the
    same structure as ordinary report fields, which the model answers happily.
    Re-adding that sentence silently kills every Claude-backed seat.
    """
    from app import routines
    prompt = routines._seat_prompt("cfo")
    for banned in ("เส้นทางการคิด", "chain of thought", "วิธีคิดภายใน",
                   "ทางนั้นถือว่าปิดแล้ว"):
        assert banned not in prompt, f"refusal trigger back in the prompt: {banned}"
    # but the seat must still be told to obey corrections and not invent numbers
    assert "fix_responses" in prompt and "ห้ามเดาตัวเลข" in prompt


def test_a_run_carrying_a_correction_is_not_folded_away(client):
    """A fix inside a collapsed older run is a fix the CEO cannot find — and
    that run is exactly where he looks to see what he changed."""
    html = client.get("/").text
    assert "const expanded = open || fixes.length > 0" in html, \
        "older runs with corrections are still collapsed"
    assert "flow${expanded ? '' : ' collapsed'}" in html


def test_history_toggles_on_its_own_flag_not_on_display(client):
    """A second click arriving while the fetch was in flight read the half-open
    box as "open" and closed it, leaving an empty div and no flow on screen."""
    html = client.get("/").text
    assert "box.dataset.open" in html, "toggle still keys off style.display"
    assert "reloadRoutineHistory" in html, "no rebuild path after a correction"
    # the old failure mode: hiding the box as the way to refresh it
    assert "style.display = 'none';\n  openRoutineHistory" not in html


def test_the_ui_serves_the_flow_and_its_edit_affordance(client):
    html = client.get("/").text
    for marker in ("renderSeatRun", "fnode", "askFix", "dropFix", "toggleFlow",
                   "fnode-fix", "fnode-fixed", "fedge", "flow-h",
                   "เส้นทางการตัดสินใจ"):
        assert marker in html, marker
