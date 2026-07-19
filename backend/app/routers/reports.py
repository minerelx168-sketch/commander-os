"""Daily report router."""
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Approval, CostEntry, Task

router = APIRouter(prefix="/api/report", tags=["reports"])


def build_daily_report(db: Session) -> str:
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)

    done = db.scalar(select(func.count(Task.id)).where(Task.status == "done", Task.updated_at >= today_start)) or 0
    in_prog = db.scalar(select(func.count(Task.id)).where(Task.status.in_(["pending", "in_progress"]))) or 0
    waiting = db.scalar(select(func.count(Approval.id)).where(Approval.status == "pending")) or 0
    cost = db.scalar(select(func.coalesce(func.sum(CostEntry.cost_thb), 0)).where(CostEntry.created_at >= today_start)) or 0

    return (
        "🧠 Commander OS — รายงานประจำวัน\n"
        f"✅ งานเสร็จวันนี้: {done}\n"
        f"⏳ งานกำลังทำ/ค้าง: {in_prog}\n"
        f"📋 รออนุมัติ: {waiting} รายการ\n"
        f"💸 ค่าใช้จ่าย LLM วันนี้: {float(cost):.2f} บาท"
    )


@router.get("/daily")
def daily(db: Session = Depends(get_db)) -> dict:
    return {"report": build_daily_report(db)}
