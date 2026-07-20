"""Voice router — push-to-talk STT command intake + TTS playback."""
from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import CommandIn
from ..services import voice as voice_svc

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/command")
async def voice_command(
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Audio in → transcript → dispatched to CEO like a typed command."""
    data = await audio.read()
    transcript = voice_svc.transcribe(data, audio.content_type or "audio/webm")

    from .commands import create_command

    out = create_command(CommandIn(text=transcript, source="voice"), background, db)
    return {"transcript": transcript, "task_id": out.task_id, "status": out.status}


@router.get("/tts")
def tts(text: str) -> Response:
    """Thai TTS — mp3 bytes for browser playback."""
    return Response(content=voice_svc.synthesize(text[:800]), media_type="audio/mpeg")
