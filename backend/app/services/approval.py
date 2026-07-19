"""Approval queue service."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Approval


def list_pending(db: Session) -> list[Approval]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)
    ).all()
    fresh = []
    for a in rows:
        exp = a.expires_at
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)  # sqlite returns naive datetimes
        if exp is not None and exp < now:
            a.status = "expired"
        else:
            fresh.append(a)
    db.commit()
    return fresh


def decide(db: Session, approval_id: int, decision: str, decided_by: str = "owner") -> Approval:
    a = db.get(Approval, approval_id)
    if a is None:
        raise ValueError(f"approval {approval_id} not found")
    if a.status != "pending":
        raise ValueError(f"approval {approval_id} already {a.status}")
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve|reject")
    a.status = "approved" if decision == "approve" else "rejected"
    a.decided_by = decided_by
    a.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(a)
    return a
