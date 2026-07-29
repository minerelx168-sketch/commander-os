"""Commander Hub — C-Suite strategic advisory board. No task automation.

Pages (single-page UI in static/index.html):
  1. Boardroom — ask a hard question scoped to a project; the board advances
     one round at a time and stops at a decision gate before each round, so
     the CEO can steer, skip, stop, rewind (reset) or branch the debate
  2. Decisions — Proven-by-Decision log: record what you decided, score the advice
  3. เอกสาร — LINE / upload / Drive knowledge library feeding the board
  4. Agents — pick which AI provider powers each advisor
"""
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, depts, docs, llm, report, research, store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Commander Hub — C-Suite Advisory")
STATIC = Path(__file__).resolve().parent.parent / "static"


class AskIn(BaseModel):
    question: str
    project: str | None = None
    web_research: bool | None = None  # None = follow WEB_RESEARCH_DEFAULT


class AdvanceIn(BaseModel):
    step: str | None = None       # None = the next pending round
    directive: str | None = None  # CEO's steer injected into this round


class StepIn(BaseModel):
    step: str


class ProviderIn(BaseModel):
    provider: str


class DecisionIn(BaseModel):
    consult_id: int | None = None
    question: str
    decision: str


class ScoreIn(BaseModel):
    outcome: str
    verdict: str  # saved | faster | neutral | missed


def _view(session: dict) -> dict:
    """Session + what the CEO may do next (drives the decision gate in the UI)."""
    nxt = depts.next_step(session)
    return {**session, "next_step": nxt,
            "next_label": depts.STEP_LABELS.get(nxt) if nxt else None,
            "steps_all": depts.STEPS, "step_labels": depts.STEP_LABELS}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "commander-hub"}


@app.get("/api/state")
def state() -> dict:
    providers = store.get_providers()
    online = depts.health_all()
    return {
        "depts": [
            {"key": k, **d, "provider": providers.get(k, "mock"),
             "provider_ready": llm.provider_ready(providers.get(k, "mock")),
             "online": online.get(k, False)}
            for k, d in config.DEPTS.items()
        ],
        "providers": [{"key": k, **v, "ready": llm.provider_ready(k)}
                      for k, v in config.PROVIDERS.items()],
        "projects": docs.list_projects(),
        "research": {"backend": research.backend(), "label": research.backend_label(),
                     "keyed": research.backend() != "duckduckgo",
                     "default_on": config.WEB_RESEARCH_DEFAULT},
        "consults": store.get_consults(8),
        "decision_stats": store.decision_stats(),
    }


# ── Boardroom: a consult advances one step at a time ──

@app.post("/api/consult")
def consult(body: AskIn) -> dict:
    """Open a session. Nothing runs yet — the caller gets an id first so STOP
    is available from the very first round, then advances step by step."""
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "question is required")
    project = (body.project or "").strip() or None
    web = config.WEB_RESEARCH_DEFAULT if body.web_research is None else body.web_research
    return _view(store.create_session(q, project, web_research=web))


@app.post("/api/consult/{session_id}/advance")
def advance(session_id: int, body: AdvanceIn) -> dict:
    """Run the next round — optionally skipping ahead or steering with a directive."""
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    step = body.step or depts.next_step(session)
    if step is None:
        raise HTTPException(400, "การประชุมจบครบทุกรอบแล้ว — แตกกิ่งหรือย้อนกลับเพื่อถกต่อ")
    if step not in depts.STEPS:
        raise HTTPException(400, f"unknown step: {step}")
    if any(s["key"] == step for s in session["steps"]):
        raise HTTPException(400, f"รอบ {step} รันไปแล้ว — ใช้ reset เพื่อรันใหม่")
    return _advance(session_id, step, (body.directive or "").strip() or None)


def _advance(session_id: int, step: str, directive: str | None) -> dict:
    store.clear_stop(session_id)
    store.set_status(session_id, "running")
    session = store.get_consult(session_id)
    try:
        results = depts.run_step(session, step, directive)
    except Exception as e:  # noqa: BLE001 — a failed round must not lose the session
        store.set_status(session_id, "awaiting")
        raise HTTPException(500, f"รอบ {step} ล้มเหลว: {str(e)[:200]}") from e
    stopped = store.is_stopped(session_id)
    store.append_step(session_id, step, results, directive)
    updated = store.set_status(
        session_id, "stopped" if stopped else
        ("done" if depts.next_step(store.get_consult(session_id)) is None else "awaiting"))
    store.clear_stop(session_id)
    return _view(updated)


@app.post("/api/consult/{session_id}/stop")
def stop(session_id: int) -> dict:
    """CEO pulls the plug: advisors still pending in this round are abandoned."""
    if store.get_consult(session_id) is None:
        raise HTTPException(404, "consult not found")
    store.request_stop(session_id)
    return _view(store.set_status(session_id, "stopped"))


@app.post("/api/consult/{session_id}/reset")
def reset(session_id: int, body: StepIn) -> dict:
    """Rewind to a round and drop everything after it (the discarded path is
    replayed to the board so it does not repeat a rejected angle)."""
    if store.get_consult(session_id) is None:
        raise HTTPException(404, "consult not found")
    if body.step not in depts.STEPS:
        raise HTTPException(400, f"unknown step: {body.step}")
    return _view(store.reset_to(session_id, body.step))


@app.post("/api/consult/{session_id}/branch")
def branch(session_id: int, body: StepIn) -> dict:
    """Fork an alternate timeline from a round, keeping the original intact."""
    if store.get_consult(session_id) is None:
        raise HTTPException(404, "consult not found")
    if body.step not in depts.STEPS:
        raise HTTPException(400, f"unknown step: {body.step}")
    child = store.branch_from(session_id, body.step)
    if child is None:
        raise HTTPException(400, f"รอบ {body.step} ยังไม่ได้รัน — แตกกิ่งไม่ได้")
    return _view(child)


# ── PDF reports: the audit trail behind each round + the executive summary ──

def _pdf(body: bytes, filename: str) -> Response:
    return Response(content=body, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@app.get("/api/consult/{session_id}/report/{step}.pdf")
def step_report(session_id: int, step: str, refresh: bool = False) -> Response:
    """Per-round report: frameworks used, numbers cited, chart, sources."""
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    if step not in depts.STEPS:
        raise HTTPException(400, f"unknown step: {step}")
    if refresh:
        report.methodology(session, step, refresh=True)
        session = store.get_consult(session_id)
    try:
        body = report.build_step_pdf(session, step)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _pdf(body, f"consult-{session_id}-{step}.pdf")


@app.get("/api/consult/{session_id}/executive-summary.pdf")
def executive_summary(session_id: int, refresh: bool = False) -> Response:
    """Board-level summary with the decision options put to the CEO."""
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    if refresh:
        report.decision_options(session, refresh=True)
        session = store.get_consult(session_id)
    try:
        body = report.build_executive_summary_pdf(session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _pdf(body, f"consult-{session_id}-executive-summary.pdf")


@app.get("/api/consult/{session_id}/options")
def options(session_id: int) -> dict:
    """The same decision options the summary prints — so the UI can offer them
    as one-click choices that land in the decision log."""
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    return report.decision_options(session)


@app.get("/api/consults")
def consults(limit: int = 10) -> dict:
    return {"consults": store.get_consults(limit)}


@app.get("/api/consults/{consult_id}")
def consult_detail(consult_id: int) -> dict:
    c = store.get_consult(consult_id)
    if c is None:
        raise HTTPException(404, "consult not found")
    return _view(c)


@app.delete("/api/consults/{consult_id}")
def delete_consult(consult_id: int) -> dict:
    if not store.delete_consult(consult_id):
        raise HTTPException(404, "consult not found")
    return {"deleted": consult_id}


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


# ── Documents: LINE / upload / Google Drive -> advisor knowledge ──

@app.get("/api/docs")
def documents(limit: int = 50) -> dict:
    return {
        "documents": docs.list_documents(limit),
        "projects": docs.list_projects(),
        "drive_connected": docs.drive_ready(),
        "line_connected": docs.line_ready(),
        "knowledge_chars": len(docs.knowledge_context()),
    }


@app.post("/api/docs/upload")
async def upload(file: UploadFile = File(...), project: str = Form("")) -> dict:
    """Upload straight from the browser — same librarian pipeline as LINE."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "ไฟล์ว่าง")
    name = Path(file.filename or "upload.bin").name
    mime = file.content_type or "application/octet-stream"
    text = None
    if mime.startswith("text/") or name.endswith((".txt", ".md", ".csv")):
        text = content.decode("utf-8", errors="replace")
    return docs.save_document(name, content, mime, "upload", text,
                              project=(project or "").strip() or None)


class ProjectIn(BaseModel):
    name: str


@app.post("/api/docs/projects")
def create_project(body: ProjectIn) -> dict:
    name = body.name.strip()
    if not name or "/" in name:
        raise HTTPException(400, "invalid project name")
    return docs.create_project(name)


@app.post("/api/docs/reclassify")
def reclassify() -> dict:
    return docs.reclassify_all()


@app.post("/api/docs/sync")
def docs_sync() -> dict:
    return docs.sync_from_drive()


@app.post("/api/line/webhook")
async def line_webhook(request: Request) -> dict:
    body = await request.body()
    if docs.line_ready() and not docs.verify_line_signature(
            body, request.headers.get("X-Line-Signature", "")):
        raise HTTPException(401, "bad LINE signature")
    import json as _json
    saved = docs.handle_line_events(_json.loads(body or b"{}"))
    return {"saved": len(saved)}
