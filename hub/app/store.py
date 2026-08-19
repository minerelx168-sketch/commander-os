"""Persistent JSON store: provider assignment, consult sessions, decision log,
pipeline routines.

A consult is a *session* that advances one step at a time so the CEO can
decide between rounds (continue / redirect / skip / stop), and can branch or
reset any step like a git history. Abandoned paths are kept in `history` so
the board can learn from the route the CEO rejected.

A routine is the other half: not one hard question but *recurring work*, with a
project, a named owner, and its own work tree of tasks. Each task keeps every
run it has ever produced instead of overwriting the last one, so a CEO comment
that corrects an answer leaves both versions on the record — what the AI said,
what it was told, and what it changed.
"""
import json
import threading
from datetime import datetime, timezone

from . import config

_LOCK = threading.Lock()
_FILE = config.MEMORY_DIR / "hub_store.json"

# Sessions the CEO asked to stop; checked between advisors mid-round.
_STOP: set[int] = set()

_DEFAULT = {
    # Each seat starts on its assigned agent; unassigned seats fall back to mock.
    "providers": {d: config.DEFAULT_PROVIDERS.get(d, "mock") for d in config.DEPTS},
    "consults": [],                                   # step-by-step board sessions
    "decisions": [],                                  # Proven-by-Decision log
    "memory": [],                                     # what past sessions concluded
    "routines": [],                                   # pipeline: recurring work trees
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(c: dict) -> dict:
    """Old records stored the three rounds flat — lift them into `steps`."""
    if "steps" in c:
        return c
    steps = [{"key": k, "results": c[k], "directive": None, "at": c.get("at")}
             for k in ("opinions", "cross_exam", "verdicts") if c.get(k)]
    return {**c, "steps": steps, "history": [], "project": c.get("project"),
            "web_research": False, "parent_id": None, "branched_from": None,
            "status": "done"}


def _load() -> dict:
    if _FILE.exists():
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        for k, v in _DEFAULT.items():
            data.setdefault(k, v)
        # A seat added after this store was written (e.g. the Researcher) would
        # otherwise stay missing forever — setdefault only guards top-level keys.
        for dept in config.DEPTS:
            data["providers"].setdefault(dept, config.DEFAULT_PROVIDERS.get(dept, "mock"))
        data["consults"] = [_migrate(c) for c in data["consults"]]
        return data
    return json.loads(json.dumps(_DEFAULT))


def _save(data: dict) -> None:
    _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def get_providers() -> dict:
    with _LOCK:
        return _load()["providers"]


def set_provider(dept: str, provider: str) -> dict:
    with _LOCK:
        data = _load()
        data["providers"][dept] = provider
        _save(data)
        return data["providers"]


def reset_providers() -> dict:
    """Back to the shipped line-up. Consults, decisions and memory are untouched
    — this resets who answers, not what the board has already concluded."""
    with _LOCK:
        data = _load()
        data["providers"] = {d: config.DEFAULT_PROVIDERS.get(d, "mock") for d in config.DEPTS}
        _save(data)
        return data["providers"]


# ── consult sessions ──

def create_session(question: str, project: str | None = None,
                   web_research: bool = True, use_docs: bool = True,
                   parent_id: int | None = None, branched_from: str | None = None,
                   steps: list | None = None, history: list | None = None,
                   seats: list | None = None) -> dict:
    entry = {"id": None, "question": question, "project": project,
             "web_research": web_research,
             # False = a general question with no tie to the CEO's own business,
             # so the document library is left out of the prompts entirely.
             "use_docs": use_docs,
             # Which seats the Frame stage convened. None until Frame runs; the
             # pipeline falls back to every seat so a session is never empty.
             "seats": seats,
             "parent_id": parent_id, "branched_from": branched_from,
             "steps": steps or [], "history": history or [],
             "status": "awaiting", "at": _now()}
    with _LOCK:
        data = _load()
        entry["id"] = max((c["id"] for c in data["consults"]), default=0) + 1
        data["consults"].append(entry)
        data["consults"] = data["consults"][-50:]
        _save(data)
    return entry


def _find(data: dict, session_id: int) -> dict | None:
    return next((c for c in data["consults"] if c["id"] == session_id), None)


def append_step(session_id: int, key: str, results: dict,
                directive: str | None = None) -> dict | None:
    with _LOCK:
        data = _load()
        c = _find(data, session_id)
        if c is None:
            return None
        c["steps"].append({"key": key, "results": results,
                           "directive": directive or None, "at": _now()})
        _save(data)
        return c


def attach_methodology(session_id: int, step_key: str, data: dict) -> None:
    """Cache the audit of how a round was reasoned, so re-downloading the PDF
    does not re-run (and re-pay for) the extraction."""
    with _LOCK:
        store = _load()
        c = _find(store, session_id)
        if c is None:
            return
        for s in c["steps"]:
            if s["key"] == step_key:
                s["methodology"] = data
                _save(store)
                return


def attach_options(session_id: int, data: dict) -> None:
    """Cache the decision options put in front of the CEO."""
    with _LOCK:
        store = _load()
        c = _find(store, session_id)
        if c is None:
            return
        c["options"] = data
        _save(store)


def attach_finmodel(session_id: int, data: dict) -> None:
    """Cache the CFO's financial-model assumptions for the Excel export."""
    with _LOCK:
        store = _load()
        c = _find(store, session_id)
        if c is None:
            return
        c["finmodel"] = data
        _save(store)


def attach_deliverable(session_id: int, dept: str, data: dict) -> None:
    """Cache a department's working document + the board's review of it."""
    with _LOCK:
        store = _load()
        c = _find(store, session_id)
        if c is None:
            return
        c.setdefault("deliverables", {})[dept] = data
        _save(store)


def set_seats(session_id: int, seats: list) -> None:
    """Record which perspectives the Frame stage convened for this question."""
    with _LOCK:
        data = _load()
        c = _find(data, session_id)
        if c is None:
            return
        c["seats"] = seats
        _save(data)


# ── pipeline: routines, each its own work tree ──
#
# A routine is a lane of recurring work — "รายงานยอดขายรายสัปดาห์", "ตรวจ
# กระแสเงินสดรายเดือน". It carries a project and a named owner because work with
# no owner is a wish, and it holds its own tasks: nothing here is shared between
# routines, so two lanes can disagree, be re-run, or be deleted independently.
#
# A task never overwrites its own output. Every execution appends a `run`, and a
# CEO comment appends a run of its own rather than editing the last one — the
# tree is the audit trail of what the AI was told and what changed because of it.

_ROUTINE_STATUSES = ("active", "paused", "archived")
_TASK_STATUSES = ("todo", "running", "review", "done", "blocked")


def _routine_of(data: dict, routine_id: int) -> dict | None:
    return next((r for r in data["routines"] if r["id"] == routine_id), None)


def _task_of(routine: dict, task_id: int) -> dict | None:
    return next((t for t in routine["tasks"] if t["id"] == task_id), None)


def add_routine(name: str, project: str | None, owner: str, dept: str,
                goal: str = "", cadence: str = "") -> dict:
    entry = {"id": None, "name": name, "project": project or None, "owner": owner,
             "dept": dept, "goal": goal or "", "cadence": cadence or "",
             "status": "active", "tasks": [], "at": _now(), "updated_at": _now()}
    with _LOCK:
        data = _load()
        entry["id"] = max((r["id"] for r in data["routines"]), default=0) + 1
        # The work tree's own name, stable for the life of the routine: it is how
        # a run, a comment and a branch are traced back to one lane of work.
        slug = _slug(name)
        entry["tree"] = f"routine/{entry['id']}-{slug}" if slug else f"routine/{entry['id']}"
        data["routines"].append(entry)
        _save(data)
    return entry


def _slug(name: str) -> str:
    """A short ASCII handle for a tree name, or "" when there is nothing to
    slug — a Thai routine name leaves the tree as `routine/<id>` rather than
    `routine/<id>-` or some invented English filler."""
    keep = [c.lower() if c.isascii() and c.isalnum() else "-" for c in (name or "")]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:32].strip("-")


def get_routines(include_archived: bool = False) -> list:
    with _LOCK:
        items = _load()["routines"]
    return [r for r in items if include_archived or r.get("status") != "archived"]


def get_routine(routine_id: int) -> dict | None:
    with _LOCK:
        return _routine_of(_load(), routine_id)


def update_routine(routine_id: int, **fields) -> dict | None:
    """Patch the routine's own attributes. `tasks` is never patched here — tasks
    move through their own calls so a stale UI cannot overwrite a run."""
    allowed = {"name", "project", "owner", "dept", "goal", "cadence", "status"}
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        if r is None:
            return None
        for k, v in fields.items():
            if k in allowed and v is not None:
                r[k] = v
        r["updated_at"] = _now()
        _save(data)
        return r


def delete_routine(routine_id: int) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["routines"])
        data["routines"] = [r for r in data["routines"] if r["id"] != routine_id]
        _save(data)
        return len(data["routines"]) < before


def add_task(routine_id: int, title: str, brief: str = "",
             owner: str | None = None, parent_task: int | None = None,
             runs: list | None = None, branched_from: int | None = None) -> dict | None:
    """Add a task to a routine's tree. `owner` falls back to the routine's owner
    so a task is never unassigned; `parent_task` records a branch's origin."""
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        if r is None:
            return None
        task = {"id": max((t["id"] for t in r["tasks"]), default=0) + 1,
                "title": title, "brief": brief or "",
                "owner": owner or r.get("owner", ""),
                "status": "todo", "runs": runs or [], "comments": [],
                # Corrections aimed at ONE node of the reasoning, not at the
                # answer as a whole — see add_correction.
                "corrections": [],
                "parent_task": parent_task, "branched_from": branched_from,
                "at": _now()}
        r["tasks"].append(task)
        r["updated_at"] = _now()
        _save(data)
        return task


def update_task(routine_id: int, task_id: int, **fields) -> dict | None:
    allowed = {"title", "brief", "owner", "status"}
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        t = _task_of(r, task_id) if r else None
        if t is None:
            return None
        for k, v in fields.items():
            if k in allowed and v is not None:
                t[k] = v
        r["updated_at"] = _now()
        _save(data)
        return t


def delete_task(routine_id: int, task_id: int) -> bool:
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        if r is None:
            return False
        before = len(r["tasks"])
        r["tasks"] = [t for t in r["tasks"] if t["id"] != task_id]
        r["updated_at"] = _now()
        _save(data)
        return len(r["tasks"]) < before


def append_run(routine_id: int, task_id: int, run: dict) -> dict | None:
    """Record one execution. Runs are appended, never replaced — the previous
    answer is the only way to see what a comment actually changed."""
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        t = _task_of(r, task_id) if r else None
        if t is None:
            return None
        entry = {**run, "n": len(t["runs"]) + 1, "at": _now()}
        t["runs"].append(entry)
        # Everything the CEO had flagged is answered by this run, whatever it says
        for c in t["comments"] + t.setdefault("corrections", []):
            if c.get("answered_by") is None:
                c["answered_by"] = entry["n"]
        t["status"] = "review" if entry.get("ok") else "blocked"
        r["updated_at"] = _now()
        _save(data)
        return t


def add_comment(routine_id: int, task_id: int, text: str,
                author: str = "CEO") -> dict | None:
    """A correction aimed at the run that is currently on top. `answered_by` stays
    None until a later run responds to it, which is what makes an unaddressed
    comment visible instead of lost in a thread."""
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        t = _task_of(r, task_id) if r else None
        if t is None:
            return None
        comment = {"id": max((c["id"] for c in t["comments"]), default=0) + 1,
                   "text": text, "author": author,
                   "on_run": len(t["runs"]) or None, "answered_by": None,
                   "at": _now()}
        t["comments"].append(comment)
        r["updated_at"] = _now()
        _save(data)
        return comment


def open_comments(task: dict) -> list:
    """Comments no run has answered yet — the CEO's outstanding corrections."""
    return [c for c in task.get("comments", []) if c.get("answered_by") is None]


def add_correction(routine_id: int, task_id: int, run_n: int, node: str,
                   label: str, was: str, should: str) -> dict | None:
    """Pin a correction to ONE node of one run's reasoning.

    A comment says "this answer is wrong". A correction says *where* it went
    wrong — which step, which assumption, which reading of the problem — and
    what it should have been. That distinction is the whole point: an answer
    rejected wholesale gives the model nothing to steer by, so it re-derives the
    same conclusion down the same road. A step marked wrong, quoted back with
    what it should say, cannot be walked again.

    `was` is captured at the moment of correction rather than looked up later:
    the run it refers to is immutable, but the CEO must be able to read what he
    rejected even if the node's index shifts in later runs.
    """
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        t = _task_of(r, task_id) if r else None
        if t is None:
            return None
        corrections = t.setdefault("corrections", [])
        entry = {"id": max((c["id"] for c in corrections), default=0) + 1,
                 "run_n": run_n, "node": node, "label": label,
                 "was": was, "should": should,
                 "answered_by": None, "at": _now()}
        corrections.append(entry)
        r["updated_at"] = _now()
        _save(data)
        return entry


def open_corrections(task: dict) -> list:
    """Wrong turns the CEO has marked that no later run has answered yet."""
    return [c for c in task.get("corrections", []) if c.get("answered_by") is None]


def branch_task(routine_id: int, task_id: int, run_n: int,
                title: str | None = None) -> dict | None:
    """Fork a task at one of its runs into a sibling in the same tree.

    The original keeps every run; the branch starts from the chosen one and is
    told which route it came from, so the CEO can hold two answers to the same
    task side by side instead of losing one to the other.
    """
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        t = _task_of(r, task_id) if r else None
        if t is None:
            return None
        kept = [json.loads(json.dumps(run)) for run in t["runs"] if run["n"] <= run_n]
        if not kept:
            return None
        # The corrections that shaped those runs travel with them: a branch that
        # forgot which turns were already ruled out would walk them again.
        fixes = [json.loads(json.dumps(c)) for c in t.get("corrections", [])
                 if c.get("run_n", 0) <= run_n]
        src_title, src_brief, src_owner = t["title"], t["brief"], t["owner"]
    branch = add_task(routine_id, title or f"{src_title} (แตกกิ่ง)", src_brief,
                      src_owner, parent_task=task_id, runs=kept, branched_from=run_n)
    if branch is None:
        return None
    with _LOCK:
        data = _load()
        r = _routine_of(data, routine_id)
        t = _task_of(r, branch["id"]) if r else None
        if t is not None:
            t["corrections"] = fixes
            _save(data)
            return t
    return branch


def pipeline_stats() -> dict:
    with _LOCK:
        routines = _load()["routines"]
    tasks = [t for r in routines for t in r["tasks"]]
    return {
        "routines": sum(1 for r in routines if r.get("status") != "archived"),
        "tasks": len(tasks),
        "done": sum(1 for t in tasks if t["status"] == "done"),
        "review": sum(1 for t in tasks if t["status"] == "review"),
        "blocked": sum(1 for t in tasks if t["status"] == "blocked"),
        "open_comments": sum(len(open_comments(t)) for t in tasks),
        "open_fixes": sum(len(open_corrections(t)) for t in tasks),
        "runs": sum(len(t["runs"]) for t in tasks),
    }


# ── persistent memory: what past sessions concluded ──

def add_memory(entry: dict) -> dict:
    """Store one distilled conclusion so later sessions can be checked against it."""
    with _LOCK:
        data = _load()
        entry = {**entry, "id": max((m["id"] for m in data["memory"]), default=0) + 1,
                 "at": _now()}
        data["memory"].append(entry)
        data["memory"] = data["memory"][-200:]
        _save(data)
        return entry


def get_memory(project: str | None = None, limit: int = 40) -> list:
    """Past conclusions, newest first. `project` scopes to one business line —
    a ruling about YourFin should not be waved at a FlowerVending question."""
    with _LOCK:
        items = _load()["memory"]
    if project:
        items = [m for m in items if m.get("project") == project]
    return items[-limit:][::-1]


def forget_memory(memory_id: int) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["memory"])
        data["memory"] = [m for m in data["memory"] if m["id"] != memory_id]
        _save(data)
        return len(data["memory"]) < before


def forget_memory_for_consult(consult_id: int) -> int:
    """Erase what the board learned from one session.

    When the CEO decides a past ruling was wrong, leaving it in memory means
    every later session is audited against a conclusion nobody stands behind.
    Returns how many entries were dropped.
    """
    with _LOCK:
        data = _load()
        before = len(data["memory"])
        data["memory"] = [m for m in data["memory"] if m.get("consult_id") != consult_id]
        _save(data)
        return before - len(data["memory"])


def set_status(session_id: int, status: str) -> dict | None:
    with _LOCK:
        data = _load()
        c = _find(data, session_id)
        if c is None:
            return None
        c["status"] = status
        _save(data)
        return c


def reset_to(session_id: int, step_key: str) -> dict | None:
    """Rewind: drop `step_key` and everything after it, keeping them in history
    so the next attempt knows which route was rejected."""
    with _LOCK:
        data = _load()
        c = _find(data, session_id)
        if c is None:
            return None
        idx = next((i for i, s in enumerate(c["steps"]) if s["key"] == step_key), None)
        if idx is None:
            return c
        dropped = c["steps"][idx:]
        c["steps"] = c["steps"][:idx]
        c["history"].extend({**s, "reason": "reset", "discarded_at": _now()} for s in dropped)
        c["status"] = "awaiting"
        _save(data)
        return c


def branch_from(session_id: int, step_key: str) -> dict | None:
    """Fork an alternate timeline that keeps everything *before* `step_key`.

    The abandoned continuation travels with the branch as history, so advisors
    are told which path was already explored and must find a different angle.
    """
    with _LOCK:
        data = _load()
        c = _find(data, session_id)
        if c is None:
            return None
        idx = next((i for i, s in enumerate(c["steps"]) if s["key"] == step_key), None)
        if idx is None:
            return None
        kept = json.loads(json.dumps(c["steps"][:idx]))
        abandoned = [{**json.loads(json.dumps(s)), "reason": "branch", "discarded_at": _now()}
                     for s in c["steps"][idx:]]
    return create_session(c["question"], c.get("project"),
                          web_research=c.get("web_research", True),
                          use_docs=c.get("use_docs", True), parent_id=session_id,
                          branched_from=step_key, steps=kept, history=abandoned,
                          seats=c.get("seats"))


def get_consults(limit: int = 10) -> list:
    with _LOCK:
        return _load()["consults"][-limit:][::-1]


def get_consult(consult_id: int) -> dict | None:
    with _LOCK:
        return _find(_load(), consult_id)


def delete_consult(consult_id: int) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["consults"])
        data["consults"] = [c for c in data["consults"] if c["id"] != consult_id]
        _save(data)
        return len(data["consults"]) < before


# ── stop signal (checked between advisors so a long round can be aborted) ──

def request_stop(session_id: int) -> None:
    _STOP.add(session_id)


def clear_stop(session_id: int) -> None:
    _STOP.discard(session_id)


def is_stopped(session_id: int) -> bool:
    return session_id in _STOP


# ── Proven by Decision: CEO records what they decided + how it turned out ──

def add_decision(consult_id: int | None, question: str, decision: str) -> dict:
    entry = {"id": None, "consult_id": consult_id, "question": question,
             "decision": decision, "outcome": None, "verdict": None, "at": _now()}
    with _LOCK:
        data = _load()
        entry["id"] = max((d["id"] for d in data["decisions"]), default=0) + 1
        data["decisions"].append(entry)
        _save(data)
    return entry


def score_decision(decision_id: int, outcome: str, verdict: str) -> dict | None:
    """verdict: 'saved' (คำปรึกษาช่วยกันความเสียหาย/ชี้จุดบอด) | 'faster' | 'neutral' | 'missed'."""
    with _LOCK:
        data = _load()
        d = next((x for x in data["decisions"] if x["id"] == decision_id), None)
        if d is None:
            return None
        d["outcome"], d["verdict"] = outcome, verdict
        d["scored_at"] = _now()
        _save(data)
        return d


def get_decision(decision_id: int) -> dict | None:
    with _LOCK:
        return next((d for d in _load()["decisions"] if d["id"] == decision_id), None)


def delete_decision(decision_id: int) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["decisions"])
        data["decisions"] = [d for d in data["decisions"] if d["id"] != decision_id]
        _save(data)
        return len(data["decisions"]) < before


def get_decisions(limit: int = 30) -> list:
    with _LOCK:
        return _load()["decisions"][-limit:][::-1]


def decision_stats() -> dict:
    with _LOCK:
        ds = _load()["decisions"]
    scored = [d for d in ds if d["verdict"]]
    return {
        "total": len(ds),
        "scored": len(scored),
        "saved": sum(1 for d in scored if d["verdict"] == "saved"),
        "faster": sum(1 for d in scored if d["verdict"] == "faster"),
        "neutral": sum(1 for d in scored if d["verdict"] == "neutral"),
        "missed": sum(1 for d in scored if d["verdict"] == "missed"),
    }
