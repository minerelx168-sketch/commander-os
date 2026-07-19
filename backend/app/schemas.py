from datetime import datetime

from pydantic import BaseModel


class CommandIn(BaseModel):
    text: str
    source: str = "api"  # api | telegram


class CommandOut(BaseModel):
    task_id: int
    thread_id: str
    status: str


class TaskOut(BaseModel):
    id: int
    title: str
    assigned_to: str
    status: str
    result: dict | None = None
    cost_thb: float = 0

    model_config = {"from_attributes": True}


class ApprovalOut(BaseModel):
    id: int
    task_id: int | None
    agent: str
    action_type: str
    payload: dict
    risk: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionIn(BaseModel):
    decision: str  # approve | reject
    decided_by: str = "owner"
