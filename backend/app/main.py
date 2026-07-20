import logging

from fastapi import FastAPI

from .config import get_settings
from .routers import approvals, commands, dashboard, deliverables, reports, voice

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Commander OS", version="0.3.0")
app.include_router(commands.router)
app.include_router(approvals.router)
app.include_router(reports.router)
app.include_router(dashboard.router)
app.include_router(voice.router)
app.include_router(deliverables.router)


@app.on_event("startup")
def startup() -> None:
    from .services.telegram_bot import start_polling_thread

    start_polling_thread()


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "llm_mock": s.llm_mock,
        "telegram_mock": s.telegram_mock,
        "meta_agent_mock": s.meta_agent_mock,
    }
