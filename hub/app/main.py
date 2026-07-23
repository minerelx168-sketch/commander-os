"""Commander Hub — C-Suite strategic advisory board. No task automation.

Pages (single-page UI in static/index.html):
  1. Boardroom — ask a hard question; 3 rounds: opinions -> cross-exam -> verdicts
  2. Decisions — Proven-by-Decision log: record what you decided, score the advice
  3. Agents — pick which AI provider powers each advisor
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, depts, llm, store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Commander Hub — C-Suite Advisory")
STATIC = Path(__file__).resolve().parent.parent / "static"


class AskIn(BaseModel):
    question: str


class ProviderIn(BaseModel):
    provider: str


class DecisionIn(BaseModel):
    consult_id: int | None = None
    question: str
    decision: str


class ScoreIn(BaseModel):
    outcome: str
    verdict: str  # saved | faster | neutral | missed


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
        "consults": store.get_consults(8),
        "decision_stats": store.decision_stats(),
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


@app.get("/api/consults/{consult_id}")
def consult_detail(consult_id: int) -> dict:
    c = store.get_consult(consult_id)
    if c is None:
        raise HTTPException(404, "consult not found")
    return c


# ── Proven by Decision ──

@app.post("/api/decisions")
def add_decision(body: DecisionIn) -> dict:
    if not body.question.strip() or not body.decision.strip():
        raise HTTPException(400, "question and decision are required")
    return store.add_decision(body.consult_id, body.question.strip(), body.decision.strip())


@app.get("/api/decisions")
def decisions(limit: int = 30) -> dict:
    return {"decisions": store.get_decisions(limit), "stats": store.decision_stats()}


@app.post("/api/decisions/{decision_id}/score")
def score_decision(decision_id: int, body: ScoreIn) -> dict:
    if body.verdict not in ("saved", "faster", "neutral", "missed"):
        raise HTTPException(400, "verdict must be saved|faster|neutral|missed")
    d = store.score_decision(decision_id, body.outcome.strip(), body.verdict)
    if d is None:
        raise HTTPException(404, "decision not found")
    return d


@app.put("/api/dept/{dept}/provider")
def set_provider(dept: str, body: ProviderIn) -> dict:
    if dept not in config.DEPTS:
        raise HTTPException(404, f"unknown dept: {dept}")
    if body.provider not in config.PROVIDERS:
        raise HTTPException(400, f"unknown provider: {body.provider}")
    return {"providers": store.set_provider(dept, body.provider)}
