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
    "researcher": {"name": "Researcher", "icon": "🔬", "role": "Evidence Desk",
                   "url": os.getenv("RESEARCHER_URL", "http://localhost:8205"),
                   "expertise": "ค้นคว้าหลักฐานภายนอก, ตรวจความน่าเชื่อถือของแหล่งข้อมูล, "
                                "market/competitor intelligence, การอ้างอิงที่ตรวจสอบย้อนได้"},
    "datalyst": {"name": "Data Analyst", "icon": "📊", "role": "Signal Layer",
                 "url": os.getenv("DATALYST_URL", "http://localhost:8204"),
                 "expertise": "วิเคราะห์ข้อมูล, สถิติ, แนวโน้ม, ความเสี่ยงเชิงตัวเลข"},
}

# AI providers selectable per C-level on the Agents page
PROVIDERS = {
    "anthropic": {"label": "Claude Opus (Anthropic)",
                  "model": os.getenv("ANTHROPIC_MODEL", "claude-opus-5")},
    "anthropic_fable": {"label": "Claude Fable (Anthropic)",
                        "model": os.getenv("ANTHROPIC_FABLE_MODEL", "claude-fable-5")},
    "gemini": {"label": "Gemini Pro (Google)",
               "model": os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")},
    "manus": {"label": "Manus", "model": os.getenv("MANUS_MODEL", "manus-1.6-agent")},
    "zai": {"label": "Z.AI (GLM)", "model": os.getenv("ZAI_MODEL", "glm-5.2")},
    "deepseek": {"label": "DeepSeek", "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")},
    "mock": {"label": "Mock (offline)", "model": "mock"},
}

# Which agent each seat runs on by default (the CEO can still switch any seat
# on the Agents page; this is only the first-run assignment).
DEFAULT_PROVIDERS = {
    "coo": "zai",                 # GLM-5.2
    "cmo": "gemini",              # Gemini 3.1 Pro
    "cfo": "anthropic_fable",     # Claude Fable 5
    "researcher": "anthropic",    # Claude Opus 5
    "datalyst": "deepseek",       # DeepSeek V4 Pro
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
MANUS_API_KEY = os.getenv("MANUS_API_KEY", "")
MANUS_API_URL = os.getenv("MANUS_API_URL", "https://api.manus.im/v1").rstrip("/").removesuffix("/chat/completions")
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
ZAI_API_URL = os.getenv("ZAI_API_URL", "https://api.z.ai/api/paas/v4/chat/completions")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")

# --- Web research: first key wins; falls back to keyless DuckDuckGo ---
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
WEB_RESEARCH_DEFAULT = os.getenv("WEB_RESEARCH_DEFAULT", "1") not in ("0", "false", "False")

# --- Documents: Google Drive + LINE ---
GDRIVE_SA_JSON = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "")   # path to service-account .json
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")            # target Drive folder
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

MEMORY_DIR = ROOT / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
