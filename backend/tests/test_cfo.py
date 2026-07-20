"""CFO node + multi-department routing tests."""
import uuid

from langgraph.checkpoint.memory import MemorySaver

from app.graph.build import _route_after_cmo, _route_after_plan
from app.graph.cfo import cfo_work


def test_routing_cfo_only():
    state = {"plan": [{"assigned_to": "cfo", "title": "x", "description": ""}]}
    assert _route_after_plan(state) == "cfo"


def test_routing_cmo_then_cfo():
    state = {"plan": [
        {"assigned_to": "cmo", "title": "x", "description": ""},
        {"assigned_to": "cfo", "title": "y", "description": ""},
    ]}
    assert _route_after_plan(state) == "cmo"
    assert _route_after_cmo(state) == "cfo"


def test_routing_no_departments():
    assert _route_after_plan({"plan": []}) == "ceo_synthesize"


def test_cfo_work_reads_costs(db):
    from app.models import CostEntry

    db.add(CostEntry(agent="ceo", model="mock", input_tokens=100,
                     output_tokens=50, cost_thb=0.5))
    db.commit()

    out = cfo_work({
        "plan": [{"assigned_to": "cfo", "title": "สรุปการเงิน", "description": ""}],
        "task_id": None,
        "department_results": {"cmo": "ads analysis"},
    })
    assert "cfo" in out["department_results"]
    assert "cmo" in out["department_results"]  # preserves earlier results
    assert len(out["department_results"]["cfo"]) > 0


def test_cfo_skips_when_not_assigned(db):
    out = cfo_work({"plan": [{"assigned_to": "cmo", "title": "x", "description": ""}]})
    assert out == {}
