"""Hub tests — stepwise board flow, decision gates, branch/reset, web research."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path)
    import app.store as store
    monkeypatch.setattr(store, "_FILE", tmp_path / "hub_store.json")
    store._STOP.clear()
    import app.docs as docs
    monkeypatch.setattr(docs, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(docs, "_META", tmp_path / "_meta.json")
    import app.depts as depts
    depts._health_cache.clear()
    monkeypatch.setattr(depts, "svc_health", lambda dept: False)
    from app.main import app
    return TestClient(app)


def _fake_chat(provider, system, user, cancel=None):
    return {"text": f"[{provider}] คำตอบทดสอบ", "provider": provider, "model": "m", "ok": True}


FAKE_SOURCES = [
    {"title": "ตลาดตู้กดอัตโนมัติไทย 2026", "url": "https://example.com/market",
     "snippet": "มูลค่าตลาด 4,200 ล้านบาท", "body": "มูลค่าตลาด 4,200 ล้านบาท เติบโต 12%",
     "query": "ขนาดตลาดตู้กดอัตโนมัติ"},
    {"title": "Vending machine competition", "url": "https://example.com/comp",
     "snippet": "average ticket 45 THB", "body": "average ticket 45 THB",
     "query": "vending competitors thailand"},
]


def _start(client, question="ควรเปิดสาขาใหม่ไหม", project=None, web=False):
    r = client.post("/api/consult", json={"question": question, "project": project,
                                          "web_research": web})
    assert r.status_code == 200
    return r.json()


def _advance(client, sid, step=None, directive=None):
    r = client.post(f"/api/consult/{sid}/advance", json={"step": step, "directive": directive})
    assert r.status_code == 200, r.text
    return r.json()


# ── state ──

def test_state_shape(client):
    s = client.get("/api/state").json()
    assert {d["key"] for d in s["depts"]} == {"cmo", "cfo", "coo", "datalyst"}
    assert {p["key"] for p in s["providers"]} >= {"anthropic", "gemini", "manus", "mock"}
    assert set(s["decision_stats"]) == {"total", "scored", "saved", "faster", "neutral", "missed"}
    # department service health is surfaced so the UI can show the online dot
    assert all("online" in d for d in s["depts"])
    # web research backend is advertised (falls back to keyless duckduckgo)
    assert s["research"]["backend"] == "duckduckgo" and s["research"]["label"]


# ── stepwise board flow with decision gates ──

def test_consult_stops_at_a_gate_before_every_round(client):
    s = _start(client)
    # creating a session runs nothing — the CEO owns the first move
    assert s["steps"] == [] and s["next_step"] == "opinions" and s["status"] == "awaiting"

    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        s = _advance(client, s["id"])
    assert [x["key"] for x in s["steps"]] == ["opinions"]
    assert s["status"] == "awaiting" and s["next_step"] == "cross_exam"
    assert m.call_count == 4  # one round only — the board waits for the CEO

    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
        s = _advance(client, s["id"])
    assert [x["key"] for x in s["steps"]] == ["opinions", "cross_exam", "verdicts"]
    assert s["next_step"] == "synthesis"

    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
    assert s["next_step"] is None and s["status"] == "done"
    assert s["steps"][-1]["results"]["chair"]["text"]


def test_ceo_directive_is_injected_into_the_round(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        s = _advance(client, s["id"], directive="เน้นความเสี่ยงกระแสเงินสดเป็นหลัก")
    assert all("เน้นความเสี่ยงกระแสเงินสดเป็นหลัก" in c.args[2] for c in m.call_args_list)
    assert s["steps"][-1]["directive"] == "เน้นความเสี่ยงกระแสเงินสดเป็นหลัก"


def test_ceo_can_skip_straight_to_the_chairman(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
        s = _advance(client, s["id"], step="synthesis")
    assert [x["key"] for x in s["steps"]] == ["opinions", "synthesis"]
    assert s["next_step"] is None and s["status"] == "done"  # synthesis is terminal


def test_rerunning_a_finished_round_is_rejected(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        _advance(client, s["id"])
    r = client.post(f"/api/consult/{s['id']}/advance", json={"step": "opinions"})
    assert r.status_code == 400 and "reset" in r.text


# ── branch & reset (git-style history the board learns from) ──

def test_reset_rewinds_and_feeds_the_rejected_path_back(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
        s = _advance(client, s["id"])
    assert len(s["steps"]) == 2

    r = client.post(f"/api/consult/{s['id']}/reset", json={"step": "cross_exam"})
    s = r.json()
    assert [x["key"] for x in s["steps"]] == ["opinions"]
    assert [h["key"] for h in s["history"]] == ["cross_exam"]
    assert s["history"][0]["reason"] == "reset" and s["next_step"] == "cross_exam"

    # the discarded round is replayed so the board must find a different angle
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        _advance(client, s["id"])
    assert all("ห้ามเสนอซ้ำแนวเดิม" in c.args[2] for c in m.call_args_list)


def test_branch_forks_an_alternate_timeline_keeping_the_original(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
        s = _advance(client, s["id"])

    child = client.post(f"/api/consult/{s['id']}/branch", json={"step": "cross_exam"}).json()
    assert child["id"] != s["id"] and child["parent_id"] == s["id"]
    assert child["branched_from"] == "cross_exam"
    assert [x["key"] for x in child["steps"]] == ["opinions"]      # kept the shared prefix
    assert child["history"][0]["reason"] == "branch"                # remembers the road not taken

    original = client.get(f"/api/consults/{s['id']}").json()
    assert [x["key"] for x in original["steps"]] == ["opinions", "cross_exam"]  # untouched


def test_branch_on_a_round_that_never_ran_is_rejected(client):
    s = _start(client)
    r = client.post(f"/api/consult/{s['id']}/branch", json={"step": "verdicts"})
    assert r.status_code == 400
    assert client.post(f"/api/consult/{s['id']}/branch", json={"step": "nope"}).status_code == 400


# ── stop ──

def test_stop_marks_the_session_and_abandons_pending_advisors(client):
    s = _start(client)
    sid = s["id"]

    def chat_then_stop(provider, system, user, cancel=None):
        client.post(f"/api/consult/{sid}/stop")   # CEO hits STOP mid-round
        return _fake_chat(provider, system, user)

    with patch("app.llm.chat", side_effect=chat_then_stop) as m:
        s = _advance(client, sid)
    assert s["status"] == "stopped"
    # every advisor holds a live cancel probe, so a slow provider (Manus polls
    # for minutes) bails out instead of waiting out its own deadline
    probes = [c.kwargs["cancel"] for c in m.call_args_list]
    assert probes and all(callable(p) for p in probes)
    # partial results are kept so nothing the board already said is lost
    assert s["steps"][0]["key"] == "opinions"
    assert len(s["steps"][0]["results"]) == 4

    # and the CEO can resume from where it stopped
    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, sid)
    assert s["status"] == "awaiting" and len(s["steps"]) == 2


def test_stop_on_unknown_session_404s(client):
    assert client.post("/api/consult/999/stop").status_code == 404


# ── web research (Round 0) ──

def test_research_round_screens_the_web_and_grounds_the_board(client):
    s = _start(client, question="ควรลงทุนตู้กดอัตโนมัติไหม", web=True)
    assert s["next_step"] == "research"

    with patch("app.research.gather", return_value=FAKE_SOURCES) as g, \
         patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
    assert g.called
    analyst = s["steps"][0]["results"]["analyst"]
    assert analyst["ok"] and analyst["queries"]
    assert [x["url"] for x in analyst["sources"]] == [x["url"] for x in FAKE_SOURCES]

    # every advisor downstream receives the screened brief with its sources
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        _advance(client, s["id"])
    for c in m.call_args_list:
        assert "ผลสืบค้นจากอินเทอร์เน็ตที่ผ่านการคัดกรองแล้ว" in c.args[2]
        assert "https://example.com/market" in c.args[2]


def test_research_failure_degrades_to_documents_only(client):
    s = _start(client, web=True)
    with patch("app.research.gather", return_value=[]), \
         patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
    analyst = s["steps"][0]["results"]["analyst"]
    assert analyst["ok"] is False and analyst["sources"] == []

    # the board still debates — a dead search backend cannot block the consult
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        s = _advance(client, s["id"])
    assert s["steps"][-1]["key"] == "opinions"
    assert all("ผลสืบค้นจากอินเทอร์เน็ต" not in c.args[2] for c in m.call_args_list)


def test_web_research_can_be_turned_off(client):
    s = _start(client, web=False)
    assert s["next_step"] == "opinions"  # Round 0 is skipped entirely


def test_search_queries_are_generated_from_the_question(client):
    s = _start(client, web=True)
    reply = {"text": "ขนาดตลาดตู้กดไทย\nvending machine market thailand\nกฎหมายตู้หยอดเหรียญ",
             "provider": "gemini", "model": "m", "ok": True}
    with patch("app.llm.chat", return_value=reply), \
         patch("app.research.gather", return_value=FAKE_SOURCES) as g:
        s = _advance(client, s["id"])
    assert g.call_args.args[0] == ["ขนาดตลาดตู้กดไทย", "vending machine market thailand",
                                   "กฎหมายตู้หยอดเหรียญ"]


def test_research_backend_selection_follows_the_keys(client, monkeypatch):
    from app import config, research
    assert research.backend() == "duckduckgo"
    monkeypatch.setattr(config, "BRAVE_API_KEY", "x")
    assert research.backend() == "brave"
    monkeypatch.setattr(config, "TAVILY_API_KEY", "y")
    assert research.backend() == "tavily"   # best available wins


def test_search_never_raises_when_the_backend_dies(client):
    from app import research
    with patch("app.research._duckduckgo", side_effect=RuntimeError("boom")):
        assert research.search("อะไรก็ได้") == []


DDG_LITE = ('<table><tr><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg='
            'https%3A%2F%2Fexample.com%2Fa&rut=x" class="result-link">หัวข้อ A</a></td></tr>'
            '<tr><td class="result-snippet">สรุป A 4,200 ล้านบาท</td></tr></table>')
DDG_HTML = ('<div><a rel="nofollow" class="result__a" href="https://example.com/b">Title B</a>'
            '<a class="result__snippet">Snippet B</a></div>')


@pytest.mark.parametrize(("markup", "url", "title"), [
    (DDG_LITE, "https://example.com/a", "หัวข้อ A"),   # href before class, link wrapped in /l/?uddg=
    (DDG_HTML, "https://example.com/b", "Title B"),    # class before href, plain link
])
def test_keyless_duckduckgo_parses_both_layouts(client, markup, url, title):
    from app import research

    class _Resp:
        text = markup

        def raise_for_status(self):
            pass

    with patch("httpx.post", return_value=_Resp()):
        hits = research._duckduckgo("อะไรก็ได้", 5)
    assert [h["url"] for h in hits] == [url]
    assert hits[0]["title"] == title and hits[0]["snippet"]


def test_duckduckgo_falls_through_to_the_second_endpoint(client):
    from app import research

    class _Resp:
        text = DDG_HTML

        def raise_for_status(self):
            pass

    with patch("httpx.post", side_effect=[RuntimeError("lite down"), _Resp()]) as p:
        hits = research._duckduckgo("อะไรก็ได้", 5)
    assert p.call_count == 2 and hits[0]["url"] == "https://example.com/b"


# ── guardrails / prompt integrity ──

def test_guardrails_in_prompts(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        _advance(client, s["id"])
    opinion_systems = [c.args[1] for c in m.call_args_list if "กฎเหล็ก" in c.args[1]]
    assert len(opinion_systems) == 4
    joined = "\n".join(opinion_systems)
    assert "ห้ามออกความเห็นเรื่องสภาพคล่อง" in joined      # CMO guardrail
    assert "ห้ามออกความเห็นเรื่องกลยุทธ์การตลาด" in joined  # CFO guardrail
    for sys_prompt in opinion_systems:
        for part in ("มุมมอง/โอกาส", "ความเสี่ยงที่ซ่อนอยู่", "คำแนะนำขั้นเด็ดขาด"):
            assert part in sys_prompt


def test_cross_exam_carries_the_other_opinions(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        s = _advance(client, s["id"])
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        _advance(client, s["id"])
    assert all("ความเห็นของที่ปรึกษาคนอื่น" in c.args[2] for c in m.call_args_list)


def test_chairman_reads_the_whole_debate(client):
    s = _start(client)
    with patch("app.llm.chat", side_effect=_fake_chat):
        for _ in range(3):
            s = _advance(client, s["id"])
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        s = _advance(client, s["id"])
    assert m.call_count == 1                       # one chairman, not four advisors
    system, user = m.call_args.args[1], m.call_args.args[2]
    assert "ประธานบอร์ด" in system and "มติบอร์ด" in system
    assert "Round 1" in user and "Round 3" in user


# ── decisions ──

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
    for marker in ("view-board", "view-decisions", "view-docs", "view-agents",
                   "askBoard", "recordDecision", "setProvider",
                   "loadDocs", "syncDrive", "step_labels",
                   # new core-flow controls
                   "ask-project", "uploadFiles", "stopBoard", "resetTo", "branchAt",
                   "researchCard", "chairCard", "ask-web", "gateBlock", "dot"):
        assert marker in html, marker
    for stale in ("view-cmo", "runTask", "LLM Learning"):
        assert stale not in html, f"stale automation marker: {stale}"


# ── documents ──

def test_docs_line_webhook_saves_text(client):
    payload = {"events": [{"type": "message",
                           "message": {"type": "text", "text": "ยอดขายเดือนนี้ 120,000 บาท"}}]}
    r = client.post("/api/line/webhook", json=payload)
    assert r.status_code == 200 and r.json()["saved"] == 1
    j = client.get("/api/docs").json()
    assert j["documents"][0]["source"] == "line"
    assert "120,000" in j["documents"][0]["text"]
    assert j["knowledge_chars"] > 0
    assert j["drive_connected"] is False  # no SA json in test env -> local mirror


def test_upload_from_browser(client):
    r = client.post("/api/docs/upload",
                    files={"file": ("plan.txt", b"runway 8 months", "text/plain")},
                    data={"project": ""})
    assert r.status_code == 200
    doc = r.json()
    assert doc["source"] == "upload" and doc["name"] == "plan.txt"
    assert "runway 8 months" in doc["text"]
    assert client.get("/api/docs").json()["documents"][0]["name"] == "plan.txt"


def test_upload_into_a_chosen_project_skips_the_librarian(client):
    client.post("/api/docs/projects", json={"name": "YourFin"})
    with patch("app.docs.classify_project") as guess:
        r = client.post("/api/docs/upload",
                        files={"file": ("loan.csv", b"a,b\n1,2", "text/csv")},
                        data={"project": "YourFin"})
    assert r.json()["project"] == "YourFin"
    guess.assert_not_called()   # the CEO already said where it goes
    import app.docs as docs
    assert (docs.LOCAL_DIR / "YourFin" / "loan.csv").exists()


def test_empty_upload_is_rejected(client):
    r = client.post("/api/docs/upload", files={"file": ("x.txt", b"", "text/plain")})
    assert r.status_code == 400


def test_docs_knowledge_feeds_consult(client):
    client.post("/api/line/webhook", json={"events": [{"type": "message",
        "message": {"type": "text", "text": "ธุรกิจของฉันคือตู้กดดอกไม้ที่เอกมัย"}}]})
    s = _start(client, question="ควรขยายไหม")
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        _advance(client, s["id"])
    users = [c.args[2] for c in m.call_args_list]
    assert all("คลังเอกสารธุรกิจของ CEO" in u and "ตู้กดดอกไม้" in u for u in users)


def test_consult_scoped_to_one_project_ignores_other_projects(client):
    client.post("/api/docs/projects", json={"name": "YourFin"})
    client.post("/api/docs/projects", json={"name": "FlowerVending"})
    with patch("app.llm.chat", return_value={"text": "YourFin", "provider": "gemini",
                                             "model": "m", "ok": True}), \
         patch("app.llm.provider_ready", return_value=True):
        client.post("/api/line/webhook", json={"events": [{"type": "message",
            "message": {"type": "text", "text": "ตารางผ่อนมือถือ งวดละ 1,200 บาท"}}]})
    with patch("app.llm.chat", return_value={"text": "FlowerVending", "provider": "gemini",
                                             "model": "m", "ok": True}), \
         patch("app.llm.provider_ready", return_value=True):
        client.post("/api/line/webhook", json={"events": [{"type": "message",
            "message": {"type": "text", "text": "ตู้ดอกไม้เอกมัยยอด 40,000"}}]})

    s = _start(client, question="ควรขยายไหม", project="YourFin")
    with patch("app.llm.chat", side_effect=_fake_chat) as m:
        _advance(client, s["id"])
    user = m.call_args.args[2]
    assert "ผ่อนมือถือ" in user and "ตู้ดอกไม้เอกมัย" not in user


def test_docs_sync_without_drive_returns_error(client):
    j = client.post("/api/docs/sync").json()
    assert j["synced"] == 0 and "Drive" in j["error"]


def test_librarian_projects_and_classification(client):
    r = client.post("/api/docs/projects", json={"name": "YourFin"})
    assert "YourFin" in r.json()["projects"]
    client.post("/api/docs/projects", json={"name": "FlowerVending"})
    assert client.post("/api/docs/projects", json={"name": "a/b"}).status_code == 400

    with patch("app.llm.chat", return_value={"text": "YourFin", "provider": "gemini",
                                             "model": "m", "ok": True}), \
         patch("app.llm.provider_ready", return_value=True):
        client.post("/api/line/webhook", json={"events": [{"type": "message",
            "message": {"type": "text", "text": "ตารางผ่อนมือถือ งวดละ 1,200 บาท"}}]})
    j = client.get("/api/docs").json()
    doc = j["documents"][0]
    assert doc["project"] == "YourFin"
    import app.docs as docs
    assert (docs.LOCAL_DIR / "YourFin" / doc["name"]).exists()
    assert "### โปรเจค: YourFin" in docs.knowledge_context()


def test_librarian_reclassify_unfiled(client):
    with patch("app.llm.chat", side_effect=_fake_chat):  # returns non-project text -> unfiled
        client.post("/api/line/webhook", json={"events": [{"type": "message",
            "message": {"type": "text", "text": "โน้ตยังไม่เข้าโปรเจค"}}]})
    client.post("/api/docs/projects", json={"name": "YourFin"})
    with patch("app.llm.chat", return_value={"text": "YourFin", "provider": "gemini",
                                             "model": "m", "ok": True}), \
         patch("app.llm.provider_ready", return_value=True):
        j = client.post("/api/docs/reclassify").json()
    assert j["filed"] == 1 and j["unfiled"] == 0


# ── history / bad inputs ──

def test_consult_history_and_delete(client):
    s = _start(client)
    assert client.get("/api/consults").json()["consults"][0]["id"] == s["id"]
    assert client.delete(f"/api/consults/{s['id']}").status_code == 200
    assert client.get(f"/api/consults/{s['id']}").status_code == 404
    assert client.delete(f"/api/consults/{s['id']}").status_code == 404


def test_bad_inputs(client):
    assert client.post("/api/consult", json={"question": "  "}).status_code == 400
    assert client.post("/api/decisions", json={"question": "", "decision": ""}).status_code == 400
    assert client.get("/api/consults/999").status_code == 404
    assert client.post("/api/consult/999/advance", json={}).status_code == 404
    assert client.post("/api/consult/999/reset", json={"step": "opinions"}).status_code == 404
