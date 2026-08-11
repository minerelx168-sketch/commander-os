"""Commander Hub — C-Suite strategic advisory board. No task automation.

Pages (single-page UI in static/index.html):
  1. Boardroom — ask a hard question scoped to a project; the board advances
     one round at a time and stops at a decision gate before each round, so
     the CEO can steer, skip, stop, rewind (reset) or branch the debate
  2. Routine — standing orders: a task the assigned seats report on daily /
     weekly / monthly (UTC+7) straight to Telegram, filed into the library
  3. Decisions — Proven-by-Decision log: record what you decided, score the advice
  4. เอกสาร — LINE / upload / Drive knowledge library feeding the board
  5. Agents — pick which AI provider powers each advisor
"""
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import (config, deliverable, depts, docs, finmodel, llm, report,
               research, routines, store, telegram)

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Commander Hub — C-Suite Advisory")
STATIC = Path(__file__).resolve().parent.parent / "static"


@app.on_event("startup")
def _start_scheduler() -> None:
    routines.start_scheduler()


# Sentinel the project picker sends for "ask this without my documents".
NO_PROJECT = "__none__"


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


class RethinkIn(BaseModel):
    direction: str | None = None   # what the CEO wants explored differently


class ScoreIn(BaseModel):
    outcome: str
    verdict: str  # saved | faster | neutral | missed


def _view(session: dict) -> dict:
    """Session + what the CEO may do next (drives the decision gate in the UI)."""
    nxt = depts.next_step(session)
    legacy = bool({s["key"] for s in session.get("steps", [])} & depts.LEGACY_STEPS)
    return {**session, "next_step": nxt,
            "next_label": depts.STEP_LABELS.get(nxt) if nxt else None,
            "steps_all": depts.STEPS, "step_labels": depts.STEP_LABELS,
            "convened": depts.seats(session), "legacy": legacy,
            "confidence": depts.confidence_summary(session)}


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
             "vendor": depts.vendor_of(providers.get(k, "mock")),
             "provider_ready": llm.provider_ready(providers.get(k, "mock")),
             "online": online.get(k, False)}
            for k, d in config.DEPTS.items()
        ],
        "providers": [{"key": k, **v, "ready": llm.provider_ready(k)}
                      for k, v in config.PROVIDERS.items()],
        "projects": docs.list_projects(),
        "research": {"backend": research.backend(), "label": research.backend_label(),
                     "keyed": bool(research.configured()),
                     "default_on": config.WEB_RESEARCH_DEFAULT},
        "diversity": depts.model_diversity(),
        "memory_count": len(store.get_memory(limit=500)),
        "consults": store.get_consults(8),
        "decision_stats": store.decision_stats(),
    }


@app.get("/api/research/diagnose")
def research_diagnose() -> dict:
    """Run one real search and report what happened.

    Without this the CEO cannot tell a blocked search engine from a subject the
    web genuinely has nothing on — both arrive as "ไม่พบหลักฐาน".
    """
    return research.diagnose()


@app.get("/api/memory")
def board_memory(project: str | None = None, limit: int = 40) -> dict:
    """What the board concluded before — the archive Frame checks against."""
    return {"memory": store.get_memory(project, limit)}


@app.delete("/api/memory/{memory_id}")
def forget(memory_id: int) -> dict:
    if not store.forget_memory(memory_id):
        raise HTTPException(404, "memory not found")
    return {"forgotten": memory_id}


# ── Boardroom: a consult advances one step at a time ──

@app.post("/api/consult")
def consult(body: AskIn) -> dict:
    """Open a session. Nothing runs yet — the caller gets an id first so STOP
    is available from the very first round, then advances step by step."""
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "question is required")
    project = (body.project or "").strip() or None
    # NO_PROJECT asks a question that has nothing to do with the CEO's own
    # business — pulling the library in would only bias the answer with numbers
    # from a different problem.
    use_docs = project != NO_PROJECT
    if not use_docs:
        project = None
    web = config.WEB_RESEARCH_DEFAULT if body.web_research is None else body.web_research
    return _view(store.create_session(q, project, web_research=web, use_docs=use_docs))


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
    # STEP_LABELS also covers the pre-Crucible stage names, so archived sessions
    # can still be exported instead of 400-ing on their own history.
    if step not in depts.STEP_LABELS:
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


@app.get("/api/consult/{session_id}/financial-model.xlsx")
def financial_model(session_id: int, refresh: bool = False) -> Response:
    """CFO scenario forecast as a live Excel model.

    Every derived cell is a formula pointing at the Assumptions sheet, so the
    CEO can change an input and re-measure without asking the board again.
    """
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    if refresh:
        finmodel.assumptions(session, refresh=True)
        session = store.get_consult(session_id)
        if session is None:  # deleted while the CFO was thinking
            raise HTTPException(404, "consult not found")
    try:
        body = finmodel.build_workbook(session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="consult-{session_id}-financial-model.xlsx"'},
    )


@app.get("/api/consult/{session_id}/financial-assumptions")
def financial_assumptions(session_id: int) -> dict:
    """The raw assumptions behind the workbook — lets the UI show which numbers
    came from the debate and which the CFO had to estimate."""
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    return finmodel.assumptions(session)


@app.get("/api/consult/{session_id}/deliverable/{dept}.pdf")
def deliverable_pdf(session_id: int, dept: str, refresh: bool = False) -> Response:
    """A department's own working document, with the board's critique attached."""
    session = store.get_consult(session_id)
    if session is None:
        raise HTTPException(404, "consult not found")
    if dept not in deliverable.SPECS:
        raise HTTPException(404, f"ไม่มีเอกสารส่งมอบสำหรับแผนก {dept}")
    if refresh:
        try:
            deliverable.build(session, dept, refresh=True)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        session = store.get_consult(session_id)
        if session is None:  # deleted mid-build
            raise HTTPException(404, "consult not found")
    try:
        body = deliverable.build_pdf(session, dept)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _pdf(body, f"consult-{session_id}-{dept}-deliverable.pdf")


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


@app.post("/api/decisions/{decision_id}/rethink")
def rethink(decision_id: int, body: RethinkIn) -> dict:
    """Take the same question down a different road.

    Branching from the Boardroom forks a stage of one meeting; branching from a
    decision reopens the question itself, which is what the CEO wants when the
    call turned out wrong and the whole framing deserves another pass.
    """
    d = store.get_decision(decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    source = store.get_consult(d["consult_id"]) if d.get("consult_id") else None
    child = store.create_session(
        d["question"],
        project=(source or {}).get("project"),
        web_research=(source or {}).get("web_research", config.WEB_RESEARCH_DEFAULT),
        use_docs=(source or {}).get("use_docs", True),
        parent_id=d.get("consult_id"),
        branched_from="decision",
    )
    return {**_view(child), "direction": (body.direction or "").strip(),
            "from_decision": decision_id}


@app.post("/api/decisions/{decision_id}/forget")
def forget_decision_learning(decision_id: int) -> dict:
    """Erase what the board learned from the consult behind this decision.

    Scoring a decision "missed" and leaving its conclusion in memory means every
    later session is still audited against advice the CEO already rejected.
    """
    d = store.get_decision(decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    if not d.get("consult_id"):
        return {"forgotten": 0, "reason": "การตัดสินใจนี้ไม่ได้ผูกกับการประชุมใด"}
    return {"forgotten": store.forget_memory_for_consult(d["consult_id"]),
            "consult_id": d["consult_id"]}


@app.delete("/api/decisions/{decision_id}")
def delete_decision(decision_id: int, forget: bool = False) -> dict:
    """Remove a decision from the log; `forget=true` also drops its learning."""
    d = store.get_decision(decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    dropped = (store.forget_memory_for_consult(d["consult_id"])
               if forget and d.get("consult_id") else 0)
    store.delete_decision(decision_id)
    return {"deleted": decision_id, "forgotten": dropped}


@app.put("/api/dept/{dept}/provider")
def set_provider(dept: str, body: ProviderIn) -> dict:
    if dept not in config.DEPTS:
        raise HTTPException(404, f"unknown dept: {dept}")
    if body.provider not in config.PROVIDERS:
        raise HTTPException(400, f"unknown provider: {body.provider}")
    return {"providers": store.set_provider(dept, body.provider)}


@app.post("/api/agents/reset")
def reset_agents() -> dict:
    """Put every seat back on its shipped agent.

    Free choice needs an undo: a CEO who has shuffled five seats while testing
    has no way back to the diverse default without editing JSON by hand.
    """
    return {"providers": store.reset_providers(),
            "diversity": depts.model_diversity()}


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


@app.delete("/api/docs/{doc_id}")
def delete_document(doc_id: int) -> dict:
    """Remove a stale or superseded document from the board's library."""
    out = docs.delete_document(doc_id)
    if out is None:
        raise HTTPException(404, "document not found")
    return out


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


# ── Routines: standing orders on a UTC+7 schedule, delivered to Telegram ──

class RoutineIn(BaseModel):
    task: str
    frequency: str                 # daily | weekly | monthly
    time: str                      # "HH:MM" in UTC+7
    day: int | None = None         # weekly 0=Mon..6=Sun; monthly 1..31
    seats: list[str] = []          # which advisors are responsible
    project: str | None = None     # scope its knowledge to one project


class RoutineToggleIn(BaseModel):
    enabled: bool


def _valid_routine(body: RoutineIn) -> tuple[str, list[str]]:
    if not body.task.strip():
        raise HTTPException(400, "task is required")
    if body.frequency not in routines.FREQUENCIES:
        raise HTTPException(400, f"frequency must be one of {routines.FREQUENCIES}")
    try:
        hh, mm = (int(x) for x in body.time.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        raise HTTPException(400, "time must be HH:MM (UTC+7)") from None
    seats = [s for s in body.seats if s in config.DEPTS]
    if not seats:
        raise HTTPException(400, "เลือกผู้รับผิดชอบอย่างน้อย 1 คน")
    return body.task.strip(), seats


@app.get("/api/routines")
def list_routines() -> dict:
    return {
        "routines": store.get_routines(),
        "runs": store.get_routine_runs(limit=20),
        "seats": [{"key": k, **v} for k, v in config.DEPTS.items()],
        "telegram_ready": telegram.ready(),
        "scheduler_alive": routines.scheduler_alive(),
        "now_local": routines.now().strftime("%Y-%m-%d %H:%M"),
    }


@app.post("/api/routines")
def create_routine(body: RoutineIn) -> dict:
    task, seats = _valid_routine(body)
    nxt = routines.next_run(body.frequency, body.time, body.day, routines.now())
    project = None if body.project in (None, "", NO_PROJECT) else body.project
    return store.add_routine(task, body.frequency, body.time, body.day,
                             seats, project, nxt.isoformat())


@app.post("/api/routines/{routine_id}/run")
def run_routine_now(routine_id: int) -> dict:
    r = store.get_routine(routine_id)
    if r is None:
        raise HTTPException(404, "routine not found")
    return routines.run_routine(r)


@app.post("/api/routines/{routine_id}/toggle")
def toggle_routine(routine_id: int, body: RoutineToggleIn) -> dict:
    r = store.update_routine(routine_id, enabled=body.enabled)
    if r is None:
        raise HTTPException(404, "routine not found")
    return r


@app.delete("/api/routines/{routine_id}")
def remove_routine(routine_id: int) -> dict:
    if not store.delete_routine(routine_id):
        raise HTTPException(404, "routine not found")
    return {"deleted": routine_id}


@app.get("/api/routines/{routine_id}/runs")
def routine_runs(routine_id: int, limit: int = 30) -> dict:
    if store.get_routine(routine_id) is None:
        raise HTTPException(404, "routine not found")
    return {"runs": store.get_routine_runs(routine_id, limit)}
