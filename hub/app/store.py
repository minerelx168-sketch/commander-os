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
    "providers": {d: "mock" for d in config.DEPTS},  # dept -> provider key
    "consults": [],                                   # step-by-step board sessions
    "decisions": [],                                  # Proven-by-Decision log
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


# ── consult sessions ──

def create_session(question: str, project: str | None = None,
                   web_research: bool = True,
                   parent_id: int | None = None, branched_from: str | None = None,
                   steps: list | None = None, history: list | None = None) -> dict:
    entry = {"id": None, "question": question, "project": project,
             "web_research": web_research,
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
                          web_research=c.get("web_research", True), parent_id=session_id,
                          branched_from=step_key, steps=kept, history=abandoned)


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
