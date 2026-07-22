"""Commander Hub — you are the CEO. FastAPI app + JSON API for the command UI.

Pages (single-page UI in static/index.html):
  1. Command Overall — ask the board; CMO/CFO/COO/Datalyst consult as a tree
  2-5. Dept task pages — assign real work per department (with LLM learning)
  6. Agents — pick which AI provider powers each C-level
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, depts, llm, store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Commander Hub — CEO Command")
STATIC = Path(__file__).resolve().parent.parent / "static"


class AskIn(BaseModel):
    question: str


class TaskIn(BaseModel):
    command: str


class ProviderIn(BaseModel):
    provider: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "commander-hub"}


@app.get("/api/state")
def state() -> dict:
    providers = store.get_providers()
    return {
        "depts": [
            {"key": k, **d, "provider": providers.get(k, "mock"),
             "provider_ready": llm.provider_ready(providers.get(k, "mock")),
             "online": depts.svc_health(k)}
            for k, d in config.DEPTS.items()
        ],
        "providers": [{"key": k, **v, "ready": llm.provider_ready(k)}
                      for k, v in config.PROVIDERS.items()],
        "consults": store.get_consults(5),
    }


@app.post("/api/consult")
def consult(body: AskIn) -> dict:
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "question is required")
    return depts.consult_all(q)


@app.get("/api/consults")
def consults(limit: int = 10) -> dict:
    return {"consults": store.get_consults(limit)}


@app.post("/api/dept/{dept}/task")
def dept_task(dept: str, body: TaskIn) -> dict:
    if dept not in config.DEPTS:
        raise HTTPException(404, f"unknown dept: {dept}")
    cmd = body.command.strip()
    if not cmd:
        raise HTTPException(400, "command is required")
    return depts.run_task(dept, cmd)


@app.get("/api/dept/{dept}/tasks")
def dept_tasks(dept: str, limit: int = 30) -> dict:
    if dept not in config.DEPTS:
        raise HTTPException(404, f"unknown dept: {dept}")
    return {"tasks": store.get_tasks(dept, limit), "lessons": store.get_lessons(dept)}


@app.put("/api/dept/{dept}/provider")
def set_provider(dept: str, body: ProviderIn) -> dict:
    if dept not in config.DEPTS:
        raise HTTPException(404, f"unknown dept: {dept}")
    if body.provider not in config.PROVIDERS:
        raise HTTPException(400, f"unknown provider: {body.provider}")
    return {"providers": store.set_provider(dept, body.provider)}
