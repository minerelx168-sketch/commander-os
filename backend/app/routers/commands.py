"""Command router — entry point for owner commands (API/Telegram)."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..database import get_db, get_sessionmaker
from ..graph.build import build_graph
from ..models import Task
from ..schemas import CommandIn, CommandOut, TaskOut

router = APIRouter(prefix="/api", tags=["commands"])


def run_graph_bg(task_id: int, thread_id: str, text: str) -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    SessionLocal = get_sessionmaker()

    result = graph.invoke({"user_command": text, "task_id": task_id}, config)
    from ..graph.build import get_pending_interrupt

    intr = get_pending_interrupt(graph, config)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        if intr is not None:
            task.status = "waiting_approval"
            task.result = {"interrupt": intr}
            # notify owner via telegram
            from ..services.telegram_bot import notify_approval
            notify_approval(intr)
        else:
            task.status = "done"
            task.result = {"report": result.get("final_report", "")}
            from ..services.telegram_bot import notify_report
            notify_report(result.get("final_report", ""))
        db.commit()


def resume_graph_bg(task_id: int, thread_id: str, decision: str) -> None:
    from langgraph.types import Command

    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(Command(resume=decision), config)

    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        task.status = "done"
        task.result = {"report": result.get("final_report", "")}
        db.commit()
    from ..services.telegram_bot import notify_report
    notify_report(result.get("final_report", ""))


@router.post("/command", response_model=CommandOut)
def create_command(
    cmd: CommandIn, background: BackgroundTasks, db: Session = Depends(get_db)
) -> CommandOut:
    thread_id = str(uuid.uuid4())
    task = Task(
        created_by="owner",
        assigned_to="ceo",
        title=cmd.text[:120],
        description=cmd.text,
        status="in_progress",
        thread_id=thread_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    background.add_task(run_graph_bg, task.id, thread_id, cmd.text)
    return CommandOut(task_id=task.id, thread_id=thread_id, status="in_progress")


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(404, "task not found")
    return TaskOut.model_validate(task)
