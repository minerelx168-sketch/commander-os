"""Persistent JSON store: provider assignment, consult sessions, decision log.

A consult is a *session* that advances one step at a time so the CEO can
decide between rounds (continue / redirect / skip / stop), and can branch or
reset any step like a git history. Abandoned paths are kept in `history` so
the board can learn from the route the CEO rejected.
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
    "routines": [],                                   # standing orders on a schedule
    "routine_runs": [],                               # every execution, newest last
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


# ── Routines: standing orders the board runs on a schedule ──

def add_routine(task: str, frequency: str, time_hhmm: str, day: int | None,
                seats: list, project: str | None, next_at: str) -> dict:
    entry = {"id": None, "task": task, "frequency": frequency, "time": time_hhmm,
             "day": day, "seats": seats, "project": project, "enabled": True,
             "next_at": next_at, "last_at": None, "created_at": _now()}
    with _LOCK:
        data = _load()
        entry["id"] = max((r["id"] for r in data["routines"]), default=0) + 1
        data["routines"].append(entry)
        _save(data)
    return entry


def get_routines() -> list:
    with _LOCK:
        return list(_load()["routines"])


def get_routine(routine_id: int) -> dict | None:
    with _LOCK:
        return next((r for r in _load()["routines"] if r["id"] == routine_id), None)


def update_routine(routine_id: int, **fields) -> dict | None:
    with _LOCK:
        data = _load()
        r = next((x for x in data["routines"] if x["id"] == routine_id), None)
        if r is None:
            return None
        r.update({k: v for k, v in fields.items() if v is not None})
        _save(data)
        return r


def delete_routine(routine_id: int) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["routines"])
        data["routines"] = [r for r in data["routines"] if r["id"] != routine_id]
        data["routine_runs"] = [x for x in data["routine_runs"] if x["routine_id"] != routine_id]
        _save(data)
        return len(data["routines"]) < before


def reschedule_routine(routine_id: int, next_at) -> None:
    with _LOCK:
        data = _load()
        r = next((x for x in data["routines"] if x["id"] == routine_id), None)
        if r is not None:
            r["next_at"] = next_at.isoformat() if hasattr(next_at, "isoformat") else next_at
            r["last_at"] = _now()
            _save(data)


def add_routine_run(routine_id: int, results: dict) -> dict:
    from datetime import timedelta
    local = datetime.now(timezone(timedelta(hours=7)))
    entry = {"id": None, "routine_id": routine_id, "results": results,
             "at": _now(), "at_local": local.strftime("%Y-%m-%d %H:%M"),
             "delivery": None}
    with _LOCK:
        data = _load()
        entry["id"] = max((x["id"] for x in data["routine_runs"]), default=0) + 1
        data["routine_runs"].append(entry)
        data["routine_runs"] = data["routine_runs"][-300:]
        _save(data)
    return entry


def mark_routine_delivery(routine_id: int, run_id: int, delivery: dict) -> None:
    with _LOCK:
        data = _load()
        run = next((x for x in data["routine_runs"] if x["id"] == run_id), None)
        if run is not None:
            run["delivery"] = delivery
            _save(data)


def get_routine_runs(routine_id: int | None = None, limit: int = 30) -> list:
    with _LOCK:
        runs = _load()["routine_runs"]
    if routine_id is not None:
        runs = [r for r in runs if r["routine_id"] == routine_id]
    return runs[-limit:][::-1]


def last_routine_run(routine_id: int) -> dict | None:
    runs = get_routine_runs(routine_id, limit=1)
    return runs[0] if runs else None
