"""Persistent JSON store: per-dept provider assignment, task log, learning notes."""
import json
import threading
from datetime import datetime, timezone

from . import config

_LOCK = threading.Lock()
_FILE = config.MEMORY_DIR / "hub_store.json"

_DEFAULT = {
    "providers": {d: "mock" for d in config.DEPTS},   # dept -> provider key
    "tasks": [],                                       # task log per dept
    "learning": {d: [] for d in config.DEPTS},         # dept -> lesson notes
    "consults": [],                                    # consult history (tree data)
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


def add_task(dept: str, command: str, result: str, provider: str) -> dict:
    entry = {"id": None, "dept": dept, "command": command, "result": result,
             "provider": provider, "at": datetime.now(timezone.utc).isoformat()}
    with _LOCK:
        data = _load()
        entry["id"] = len(data["tasks"]) + 1
        data["tasks"].append(entry)
        _save(data)
    return entry


def get_tasks(dept: str | None = None, limit: int = 30) -> list:
    with _LOCK:
        tasks = _load()["tasks"]
    if dept:
        tasks = [t for t in tasks if t["dept"] == dept]
    return tasks[-limit:][::-1]


def add_lesson(dept: str, lesson: str) -> None:
    with _LOCK:
        data = _load()
        data["learning"][dept] = (data["learning"].get(dept, []) + [lesson])[-20:]
        _save(data)


def get_lessons(dept: str) -> list:
    with _LOCK:
        return _load()["learning"].get(dept, [])


def add_consult(question: str, answers: dict) -> dict:
    entry = {"id": None, "question": question, "answers": answers,
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
