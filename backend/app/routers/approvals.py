"""Approval router — list pending, decide, resume graph."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Task
from ..schemas import ApprovalOut, DecisionIn
from ..services import approval as approval_svc

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_pending(db: Session = Depends(get_db)) -> list[ApprovalOut]:
    return [ApprovalOut.model_validate(a) for a in approval_svc.list_pending(db)]


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
def decide(
    approval_id: int,
    body: DecisionIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ApprovalOut:
    try:
        a = approval_svc.decide(db, approval_id, body.decision, body.decided_by)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # resume the paused graph for this task
    if a.task_id:
        task = db.get(Task, a.task_id)
        if task is not None and task.thread_id:
            from .commands import resume_graph_bg
            background.add_task(resume_graph_bg, task.id, task.thread_id, body.decision)

    return ApprovalOut.model_validate(a)
