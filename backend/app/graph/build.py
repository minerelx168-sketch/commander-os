"""Build the Commander LangGraph: ceo_plan -> cmo -> ceo_synthesize."""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .ceo import ceo_plan, ceo_synthesize
from .cmo import cmo_work
from .state import CommanderState

_graph = None
_checkpointer = None


def _route_after_plan(state: CommanderState) -> str:
    plan = state.get("plan", [])
    if any(t["assigned_to"] == "cmo" for t in plan):
        return "cmo"
    return "ceo_synthesize"


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
    g.add_node("ceo_synthesize", ceo_synthesize)

    g.add_edge(START, "ceo_plan")
    g.add_conditional_edges("ceo_plan", _route_after_plan, ["cmo", "ceo_synthesize"])
    g.add_edge("cmo", "ceo_synthesize")
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
