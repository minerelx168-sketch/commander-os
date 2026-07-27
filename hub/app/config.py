"""Commander Hub configuration — you are the CEO; departments are consultants/executors."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PORT = int(os.getenv("HUB_PORT", "8100"))

# Department services (from the template repos, run locally)
DEPTS = {
    "cmo": {"name": "CMO", "icon": "📣", "role": "Market Voice",
            "url": os.getenv("CMO_URL", "http://localhost:8201"),
            "expertise": "การตลาด omnichannel, งบโฆษณา, ROAS/CAC, กลยุทธ์ growth"},
    "cfo": {"name": "CFO", "icon": "💰", "role": "Finance Radar",
            "url": os.getenv("CFO_URL", "http://localhost:8203"),
            "expertise": "P&L, cash flow, runway, ความเสี่ยงการเงิน, การลงทุน"},
    "coo": {"name": "COO", "icon": "🛰", "role": "Operations",
            "url": os.getenv("COO_URL", "http://localhost:8202"),
            "expertise": "ปฏิบัติการหลังบ้าน, เอกสาร/สัญญา, pipeline, กระบวนการทำงาน"},
    "datalyst": {"name": "Datalyst", "icon": "📊", "role": "Signal Layer",
                 "url": os.getenv("DATALYST_URL", "http://localhost:8204"),
                 "expertise": "วิเคราะห์ข้อมูล, สถิติ, แนวโน้ม, ความเสี่ยงเชิงตัวเลข"},
}

# AI providers selectable per C-level on the Agents page
PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "model": os.getenv("ANTHROPIC_MODEL", "claude-fable-5")},
    "gemini": {"label": "Gemini (Google)", "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash")},
    "manus": {"label": "Manus", "model": os.getenv("MANUS_MODEL", "manus-1.6-agent")},
    "mock": {"label": "Mock (offline)", "model": "mock"},
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
MANUS_API_KEY = os.getenv("MANUS_API_KEY", "")
MANUS_API_URL = os.getenv("MANUS_API_URL", "https://api.manus.im/v1").rstrip("/").removesuffix("/chat/completions")

# --- Documents: Google Drive + LINE ---
GDRIVE_SA_JSON = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "")   # path to service-account .json
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")            # target Drive folder
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

MEMORY_DIR = ROOT / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
