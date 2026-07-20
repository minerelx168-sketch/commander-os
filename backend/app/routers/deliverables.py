"""Deliverables router — list and read the Markdown briefs produced per task."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..services import deliverable

router = APIRouter(prefix="/api/deliverables", tags=["deliverables"])


@router.get("")
def list_deliverables() -> dict:
    return {"briefs": deliverable.list_briefs()}


@router.get("/{filename}", response_class=PlainTextResponse)
def get_deliverable(filename: str) -> str:
    content = deliverable.read_brief(filename)
    if content is None:
        raise HTTPException(404, "brief not found")
    return content
