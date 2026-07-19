"""Graph flow tests: plan -> cmo (interrupt) -> resume -> synthesize."""
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.graph.build import build_graph, get_pending_interrupt
from app.models import Approval


def test_full_flow_with_approval_interrupt(db):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph.invoke({"user_command": "วิเคราะห์แคมเปญวันนี้", "task_id": None}, config)

    # mock recommendations exist -> graph must pause at interrupt
    intr = get_pending_interrupt(graph, config)
    assert intr is not None
    assert intr["action"] == "DECREASE_BUDGET"

    # approval record created
    approval = db.query(Approval).one()
    assert approval.status == "pending"
    assert approval.agent == "cmo"

    # resume with approval -> reaches synthesize -> final report
    result2 = graph.invoke(Command(resume="approve"), config)
    assert "final_report" in result2
    assert len(result2["final_report"]) > 0
    assert result2["approval_decision"] == "approve"


def test_plan_routes_to_cmo(db):
    from app.graph.ceo import ceo_plan

    out = ceo_plan({"user_command": "วิเคราะห์แคมเปญ", "task_id": None})
    assert out["plan"][0]["assigned_to"] == "cmo"
