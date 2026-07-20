"""LLM service — MOCK-first, with cost tracking to cost_entries."""
import json

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import CostEntry

MOCK_RESPONSES: dict[str, str] = {
    "ceo_plan": json.dumps(
        {
            "subtasks": [
                {
                    "assigned_to": "cmo",
                    "title": "วิเคราะห์ประสิทธิภาพแคมเปญ Meta Ads ล่าสุด",
                    "description": "ดึง dashboard และ recommendations จาก meta-ads-agent แล้วสรุป",
                }
            ]
        },
        ensure_ascii=False,
    ),
    "ceo_synthesize": (
        "📊 สรุปรายงานจาก CEO\n\n"
        "CMO วิเคราะห์แคมเปญแล้ว: มี 1 ข้อเสนอปรับงบรออนุมัติ "
        "แคมเปญหลักยัง ROAS ดี แนะนำติดตามต่อ"
    ),
    "cmo_analyze": (
        "วิเคราะห์แล้ว: แคมเปญ A มี CPA สูงกว่าเป้า 15% — "
        "แนะนำลดงบ 20% และมี recommendation PENDING ในระบบ meta-ads-agent"
    ),
    "cfo_analyze": (
        "การเงินสรุป: ค่าโฆษณารวม 6,000 บาท ค่า LLM สะสมต่ำ — "
        "Campaign B คุ้มสุด (ROAS 3.4) แนะนำคุมงบ Campaign A"
    ),
    "boardroom_cmo": (
        "CMO เห็นด้วยกับ CFO เรื่องคุมงบ Campaign A "
        "แต่ขอคงงบ Campaign B ไว้เพราะ ROAS ยังโตต่อได้"
    ),
    "boardroom_cfo": (
        "CFO เห็นต่างเล็กน้อย: เสนอย้ายงบ 10% จาก A ไป B "
        "เพราะตัวเลข ROAS 3.4 คุ้มกว่าอย่างมีนัยสำคัญ"
    ),
    "ceo_decide": (
        "มติ: อนุมัติย้ายงบ 10% จาก Campaign A ไป B ตามข้อเสนอ CFO "
        "และให้ CMO ติดตาม ROAS รายวัน 7 วัน แล้วรายงานกลับ"
    ),
}


def _mock_complete(purpose: str) -> tuple[str, int, int]:
    text = MOCK_RESPONSES.get(purpose, f"[MOCK:{purpose}]")
    return text, 500, 200


def _extract_text(content) -> str:
    """Normalize LLM message content to plain text.

    Claude (Fable/Sonnet 5) returns a LIST of content blocks — possibly with
    thinking blocks first; str() on that list leaks signatures into reports.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(p for p in parts if p).strip()
    return str(content)


def _resolve_model(settings, agent: str) -> tuple[str, str]:
    """(provider, model) for an agent — per-agent override, else global default.

    CEO runs on Claude Fable 5 (settings.ceo_model) when an anthropic key exists;
    otherwise falls back to the global provider so the system never bricks.
    """
    override = getattr(settings, f"{agent}_model", "")
    if override and ":" in override:
        provider, model = override.split(":", 1)
        key_ok = (provider == "anthropic" and settings.anthropic_api_key) or (
            provider == "gemini" and settings.google_api_key
        )
        if key_ok:
            return provider, model
    return settings.llm_provider, settings.llm_model


def complete(
    db: Session,
    *,
    agent: str,
    purpose: str,
    system: str,
    user: str,
    task_id: int | None = None,
) -> str:
    """Call the LLM (or mock), record cost, return the text."""
    settings = get_settings()

    if settings.llm_mock:
        text, in_tok, out_tok = _mock_complete(purpose)
        model_used = "mock"
    else:
        provider, model_used = _resolve_model(settings, agent)
        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=model_used,
                google_api_key=settings.google_api_key,
                max_output_tokens=4096,
            )
        else:
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(
                model=model_used,
                api_key=settings.anthropic_api_key,
                max_tokens=4096,
            )
        msg = llm.invoke([("system", system), ("user", user)])
        text = _extract_text(msg.content)
        usage = getattr(msg, "usage_metadata", None) or {}
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)

    cost_thb = (
        in_tok / 1_000_000 * settings.price_input_thb_per_mtok
        + out_tok / 1_000_000 * settings.price_output_thb_per_mtok
    )
    db.add(
        CostEntry(
            agent=agent,
            task_id=task_id,
            model=model_used,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_thb=cost_thb,
        )
    )
    db.commit()
    return text
