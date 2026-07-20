"""Boardroom (inter-department discussion + CEO decision) and model routing tests."""
from app.graph.boardroom import boardroom
from app.graph.build import _route_after_dept
from app.services.llm import _resolve_model


def test_route_to_boardroom_needs_two_departments():
    assert _route_after_dept({"department_results": {"cmo": "a", "cfo": "b"}}) == "boardroom"
    assert _route_after_dept({"department_results": {"cfo": "b"}}) == "ceo_synthesize"
    assert _route_after_dept({}) == "ceo_synthesize"


def test_boardroom_skips_single_department(db):
    assert boardroom({"department_results": {"cmo": "only me"}, "user_command": "x"}) == {}


def test_boardroom_discussion_and_ceo_decision(db):
    from app.models import AuditLog

    out = boardroom({
        "user_command": "วิเคราะห์แคมเปญและการเงิน",
        "task_id": None,
        "department_results": {"cmo": "ads ok", "cfo": "budget tight"},
    })
    speakers = [m["speaker"] for m in out["boardroom_log"]]
    assert speakers == ["cmo", "cfo", "ceo"]        # both depts speak, CEO rules last
    assert out["ceo_decision"].startswith("มติ")
    events = {e.event for e in db.query(AuditLog).all()}
    assert {"boardroom_comment", "boardroom_decision"} <= events


def test_ceo_model_is_claude_fable5_with_key(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "sk-test")
    assert _resolve_model(s, "ceo") == ("anthropic", "claude-fable-5")
    # departments without overrides use the global default
    assert _resolve_model(s, "cmo") == (s.llm_provider, s.llm_model)


def test_ceo_model_falls_back_without_key(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "")
    assert _resolve_model(s, "ceo") == (s.llm_provider, s.llm_model)


def test_extract_text_handles_claude_content_blocks():
    from app.services.llm import _extract_text

    assert _extract_text("plain") == "plain"
    blocks = [
        {"type": "thinking", "thinking": "secret", "signature": "CAIS..."},
        {"type": "text", "text": "รายงานจริง"},
        {"type": "text", "text": "บรรทัดสอง"},
    ]
    out = _extract_text(blocks)
    assert out == "รายงานจริง\nบรรทัดสอง"
    assert "signature" not in out and "secret" not in out


def test_daily_activity_grouped_by_day_and_dept(client, db):
    from app.models import AuditLog

    db.add_all([
        AuditLog(agent="cmo", event="analysis_done", detail={"message": "วิเคราะห์แคมเปญ"}),
        AuditLog(agent="cfo", event="finance_analysis_done", detail={}),
        AuditLog(agent="ceo", event="boardroom_decision", detail={"message": "มติ: ok"}),
    ])
    db.commit()

    r = client.get("/api/activity/daily?days=7")
    assert r.status_code == 200
    days = r.json()["days"]
    assert len(days) == 1
    (_, by_dept), = days.items()
    assert set(by_dept) == {"cmo", "cfo", "ceo"}
    assert by_dept["ceo"][0]["summary"] == "มติ: ok"
