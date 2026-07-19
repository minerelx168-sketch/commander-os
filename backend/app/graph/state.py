from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SubTask(TypedDict):
    assigned_to: str
    title: str
    description: str


class CommanderState(TypedDict, total=False):
    user_command: str
    task_id: int
    plan: list[SubTask]
    department_results: dict[str, str]
    pending_approval_id: int | None
    approval_decision: str | None      # approve | reject (set on resume)
    final_report: str
    messages: Annotated[list, add_messages]
