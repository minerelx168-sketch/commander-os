"""Build the Commander LangGraph: ceo_plan -> depts -> boardroom -> ceo_synthesize."""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .boardroom import boardroom
from .ceo import ceo_plan, ceo_synthesize
from .cfo import cfo_work
from .cmo import cmo_work
from .state import CommanderState

_graph = None
_checkpointer = None


def _route_after_plan(state: CommanderState) -> str:
    assigned = {t["assigned_to"] for t in state.get("plan", [])}
    if "cmo" in assigned:
        return "cmo"
    if "cfo" in assigned:
        return "cfo"
    return "ceo_synthesize"


def _route_after_cmo(state: CommanderState) -> str:
    assigned = {t["assigned_to"] for t in state.get("plan", [])}
    return "cfo" if "cfo" in assigned else "ceo_synthesize"


def _route_after_dept(state: CommanderState) -> str:
    """2+ departments spoke → boardroom debate; otherwise straight to synthesis."""
    return "boardroom" if len(state.get("department_results") or {}) >= 2 else "ceo_synthesize"


def get_checkpointer():
    """MemorySaver for tests/dev; swap to PostgresSaver in production."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
    return _checkpointer


def build_graph(checkpointer=None):
    global _graph
    if _graph is not None and checkpointer is None:
        return _graph

    g = StateGraph(CommanderState)
    g.add_node("ceo_plan", ceo_plan)
    g.add_node("cmo", cmo_work)
    g.add_node("cfo", cfo_work)
    g.add_node("boardroom", boardroom)
    g.add_node("ceo_synthesize", ceo_synthesize)

    g.add_edge(START, "ceo_plan")
    g.add_conditional_edges("ceo_plan", _route_after_plan, ["cmo", "cfo", "ceo_synthesize"])
    g.add_conditional_edges("cmo", _route_after_cmo, ["cfo", "ceo_synthesize"])
    g.add_conditional_edges("cfo", _route_after_dept, ["boardroom", "ceo_synthesize"])
    g.add_edge("boardroom", "ceo_synthesize")
    g.add_edge("ceo_synthesize", END)

    compiled = g.compile(checkpointer=checkpointer or get_checkpointer())
    if checkpointer is None:
        _graph = compiled
    return compiled


def get_pending_interrupt(graph, config) -> dict | None:
    """Return the pending interrupt payload for a thread, or None if finished."""
    state = graph.get_state(config)
    for task in state.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None
