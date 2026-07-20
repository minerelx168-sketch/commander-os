"""Deliverable service — turn a finished task into a real Markdown brief
(the "Intelligence Brief" pattern): directive, per-department findings,
boardroom transcript, CEO ruling, final report. Files live under
<repo>/deliverables and are served by the deliverables router.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

DELIVERABLES_DIR = Path(__file__).resolve().parents[2] / "deliverables"

DEPT_TH = {"ceo": "CEO — ผู้บริหาร", "cmo": "CMO — การตลาด", "cfo": "CFO — การเงิน"}


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^\wก-๙]+", "-", text.strip())[:limit].strip("-")
    return s or "brief"


def build_brief(task_id: int, user_command: str, state: dict) -> str:
    """Render the graph's final state into a Markdown brief; return filename."""
    now = datetime.now(timezone.utc).astimezone()
    lines = [
        f"# 🧠 Commander OS — Executive Brief #{task_id}",
        "",
        f"- **วันที่**: {now.strftime('%Y-%m-%d %H:%M')}",
        f"- **คำสั่งจากเจ้าของ**: {user_command}",
        "",
    ]

    results = state.get("department_results") or {}
    if results:
        lines += ["## 📌 ผลการทำงานรายแผนก", ""]
        for dept, text in results.items():
            lines += [f"### {DEPT_TH.get(dept, dept.upper())}", "", str(text), ""]

    board = state.get("boardroom_log") or []
    if board:
        lines += ["## 🏛 บันทึกการประชุมบอร์ด", ""]
        for m in board:
            who = DEPT_TH.get(m.get("speaker", ""), str(m.get("speaker", "")).upper())
            lines += [f"> **{who}**: {m.get('message', '')}", ""]

    if state.get("ceo_decision"):
        lines += ["## ⚖️ มติ CEO", "", state["ceo_decision"], ""]

    if state.get("final_report"):
        lines += ["## 📊 รายงานสรุปถึงเจ้าของ", "", state["final_report"], ""]

    lines += ["---", "*จัดทำอัตโนมัติโดย Commander OS*", ""]

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y%m%d')}_task{task_id}_{_slug(user_command)}.md"
    (DELIVERABLES_DIR / fname).write_text("\n".join(lines), encoding="utf-8")
    return fname


def list_briefs() -> list[dict]:
    if not DELIVERABLES_DIR.exists():
        return []
    out = []
    for p in sorted(DELIVERABLES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({
            "filename": p.name,
            "size_kb": round(p.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return out


def read_brief(filename: str) -> str | None:
    # no path traversal — serve only direct .md children of the deliverables dir
    if "/" in filename or "\\" in filename or not filename.endswith(".md"):
        return None
    p = DELIVERABLES_DIR / filename
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")
