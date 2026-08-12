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

# AI providers selectable per C-level on the Agents page.
# `vendor` is what makes this a Crucible rather than a costume party: two seats
# on the same vendor share training data, refusal habits and blind spots, so
# their "disagreement" is theatre. The board surfaces vendor overlap instead of
# trusting whoever configured it to remember.
PROVIDERS = {
    "anthropic": {"label": "Claude Opus (Anthropic)", "vendor": "Anthropic",
                  "model": os.getenv("ANTHROPIC_MODEL", "claude-opus-5")},
    "anthropic_sonnet": {"label": "Claude Sonnet (Anthropic)", "vendor": "Anthropic",
                         "model": os.getenv("ANTHROPIC_SONNET_MODEL", "claude-sonnet-5")},
    "anthropic_fable": {"label": "Claude Fable (Anthropic)", "vendor": "Anthropic",
                        "model": os.getenv("ANTHROPIC_FABLE_MODEL", "claude-fable-5")},
    "gemini": {"label": "Gemini Pro (Google)", "vendor": "Google",
               "model": os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")},
    "manus": {"label": "Manus", "vendor": "Manus",
              "model": os.getenv("MANUS_MODEL", "manus-1.6-agent")},
    "zai": {"label": "Z.AI (GLM)", "vendor": "Z.AI",
            "model": os.getenv("ZAI_MODEL", "glm-5.2")},
    "deepseek": {"label": "DeepSeek", "vendor": "DeepSeek",
                 "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")},
    "mock": {"label": "Mock (offline)", "vendor": "—", "model": "mock"},
}

# Which agent each seat runs on by default (the CEO can still switch any seat
# on the Agents page; this is only the first-run assignment).
DEFAULT_PROVIDERS = {
    "coo": "zai",                   # GLM-5.2
    "cmo": "gemini",                # Gemini 3.1 Pro
    "cfo": "anthropic_fable",       # Claude Fable 5
    "researcher": "anthropic_sonnet",  # Claude Sonnet 5
    "datalyst": "deepseek",         # DeepSeek V4 Pro
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
MANUS_API_KEY = os.getenv("MANUS_API_KEY", "")
MANUS_API_URL = os.getenv("MANUS_API_URL", "https://api.manus.im/v1").rstrip("/").removesuffix("/chat/completions")
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
ZAI_API_URL = os.getenv("ZAI_API_URL", "https://api.z.ai/api/paas/v4/chat/completions")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")

# --- Web research: keyed indexes only, tried in priority order. No keyless
# fallback: scraped engines answer bot checks that parse as zero results, and
# "no evidence" must mean the web is quiet, not that the scraper was blocked. ---
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")  # serper.dev — cheap Google index
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")  # serpapi.com — Google + engines
WEB_RESEARCH_DEFAULT = os.getenv("WEB_RESEARCH_DEFAULT", "1") not in ("0", "false", "False")

# --- Documents: Google Drive + LINE ---
GDRIVE_SA_JSON = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "")   # path to service-account .json
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")            # target Drive folder
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

MEMORY_DIR = ROOT / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

# --- Machine access (Hermes and any other automation) ---
# Empty means the API stays open, which is correct for a laptop-only hub and
# wrong the moment it is exposed; setting the key turns enforcement on.
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
