"""Persist budget commands as an approvable queue (JSON). Nothing executes here —
this is the human-in-the-loop gate. A separate approval step would flip statuses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .budget import BudgetCommand


def write_queue(commands: list[BudgetCommand], commands_dir: Path, run_id: str) -> Path:
    commands_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requires_approval": True,
        "summary": {
            "total_commands": len(commands),
            "increase": sum(1 for c in commands if c.action == "INCREASE"),
            "decrease": sum(1 for c in commands if c.action == "DECREASE"),
            "pause": sum(1 for c in commands if c.action == "PAUSE"),
            "net_budget_delta": round(sum(c.delta for c in commands), 2),
        },
        "commands": [c.as_dict() for c in commands],
    }
    out = commands_dir / f"command_queue_{run_id}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    # also maintain a stable "latest" pointer for the dashboard
    latest = commands_dir / "latest.json"
    with open(latest, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return out
