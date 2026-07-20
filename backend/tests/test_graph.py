"""Graph flow tests: plan -> cmo -> boardroom -> owner_gate (interrupt) -> resume."""
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.graph.build import build_graph, get_pending_interrupt
from app.models import Approval, AuditLog


def test_full_flow_boardroom_before_owner(db):
    """Departments discuss + CEO rules BEFORE the owner sees a single approval."""
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph.invoke({"user_command": "วิเคราะห์แคมเปญวันนี้", "task_id": None}, config)

    # mock recommendations exist -> graph pauses AFTER the boardroom, at owner_gate
    intr = get_pending_interrupt(graph, config)
    assert intr is not None
    assert intr["action"] == "DECREASE_BUDGET"
    assert "ceo_ruling" in intr and intr["ceo_ruling"]  # board already ruled

    # boardroom debated BEFORE the interrupt reached the owner
    events = [e.event for e in db.query(AuditLog).all()]
    assert "boardroom_comment" in events
    assert "boardroom_decision" in events

    # single approval, raised by the CEO (post-board), carrying board opinions
    approval = db.query(Approval).one()
    assert approval.status == "pending"
    assert approval.agent == "ceo"
    assert approval.payload.get("board_opinions")
    assert approval.payload.get("ceo_ruling")

    # resume with approval -> reaches synthesize -> final report
    result2 = graph.invoke(Command(resume="approve"), config)
    assert "final_report" in result2
    assert len(result2["final_report"]) > 0
    assert result2["approval_decision"] == "approve"

    # node re-run on resume must NOT duplicate the approval (idempotency)
    assert db.query(Approval).count() == 1


def test_plan_routes_to_cmo(db):
    from app.graph.ceo import ceo_plan

    out = ceo_plan({"user_command": "วิเคราะห์แคมเปญ", "task_id": None})
    assert out["plan"][0]["assigned_to"] == "cmo"
