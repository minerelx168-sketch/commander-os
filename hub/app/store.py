"""Persistent JSON store: provider assignment, consult history, decision log."""
import json
import threading
from datetime import datetime, timezone

from . import config

_LOCK = threading.Lock()
_FILE = config.MEMORY_DIR / "hub_store.json"

_DEFAULT = {
    "providers": {d: "mock" for d in config.DEPTS},  # dept -> provider key
    "consults": [],                                   # 3-round board sessions
    "decisions": [],                                  # Proven-by-Decision log
}


def _load() -> dict:
    if _FILE.exists():
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        for k, v in _DEFAULT.items():
            data.setdefault(k, v)
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


def add_consult(question: str, rounds: dict) -> dict:
    entry = {"id": None, "question": question, **rounds,
             "at": datetime.now(timezone.utc).isoformat()}
    with _LOCK:
        data = _load()
        entry["id"] = len(data["consults"]) + 1
        data["consults"].append(entry)
        data["consults"] = data["consults"][-50:]
        _save(data)
    return entry


def get_consults(limit: int = 10) -> list:
    with _LOCK:
        return _load()["consults"][-limit:][::-1]


def get_consult(consult_id: int) -> dict | None:
    with _LOCK:
        return next((c for c in _load()["consults"] if c["id"] == consult_id), None)


# ── Proven by Decision: CEO records what they decided + how it turned out ──

def add_decision(consult_id: int | None, question: str, decision: str) -> dict:
    entry = {"id": None, "consult_id": consult_id, "question": question,
             "decision": decision, "outcome": None, "verdict": None,
             "at": datetime.now(timezone.utc).isoformat()}
    with _LOCK:
        data = _load()
        entry["id"] = len(data["decisions"]) + 1
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
        d["scored_at"] = datetime.now(timezone.utc).isoformat()
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
