"""API-key auth for machine callers (Hermes, scripts, cron).

The hub is reachable from the internet through a tunnel, so `/api/*` must not
be world-writable. A caller proves itself with either header:

    X-Hermes-API-Key: <key>
    Authorization: Bearer <key>

The dashboard is a browser and cannot send headers on a plain navigation, so
visiting `/?key=<key>` once exchanges the key for an httpOnly cookie; the
CEO's own browser then works normally while anonymous callers do not.

Deliberate exemptions:
  * `/` and `/health`   — the dashboard has to load and monitors have to ping;
    neither exposes data.
  * `/api/line/webhook` and `/api/sources/{id}/webhook` — third-party systems
    push here and cannot send our key; they carry their own signature/secret.

With no HERMES_API_KEY set the middleware stays out of the way entirely, so a
laptop-only hub keeps working exactly as before.
"""
import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from . import config

COOKIE = "hermes_key"
OPEN_PATHS = {"/", "/health", "/favicon.ico", "/docs", "/openapi.json", "/redoc",
              "/api/ingest"}   # authenticates with its own per-connector key
OPEN_SUFFIXES = ("/webhook",)          # inbound pushes authenticate their own way


def _presented(request: Request) -> str:
    key = request.headers.get("X-Hermes-API-Key", "")
    if key:
        return key
    auth = request.headers.get("Authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return request.cookies.get(COOKIE, "")


def valid(presented: str) -> bool:
    """True when the key matches — or when no key is configured at all."""
    if not config.HERMES_API_KEY:
        return True
    # compare_digest: reject on content, not on how early the bytes differ
    return hmac.compare_digest(presented, config.HERMES_API_KEY)


def is_open(path: str) -> bool:
    return (path in OPEN_PATHS
            or not path.startswith("/api/")
            or path.endswith(OPEN_SUFFIXES))


async def require_api_key(request: Request, call_next):
    if config.HERMES_API_KEY and not is_open(request.url.path):
        if not valid(_presented(request)):
            return JSONResponse(
                {"detail": "unauthorized — ส่ง X-Hermes-API-Key หรือ "
                           "Authorization: Bearer <key>"},
                status_code=401)
    return await call_next(request)
