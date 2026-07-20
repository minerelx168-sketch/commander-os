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
}


def _mock_complete(purpose: str) -> tuple[str, int, int]:
    text = MOCK_RESPONSES.get(purpose, f"[MOCK:{purpose}]")
    return text, 500, 200


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
    else:
        if settings.llm_provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=settings.llm_model,
                google_api_key=settings.google_api_key,
                max_output_tokens=4096,
            )
        else:
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(
                model=settings.llm_model,
                api_key=settings.anthropic_api_key,
                max_tokens=4096,
            )
        msg = llm.invoke([("system", system), ("user", user)])
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
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
            model=settings.llm_model if not settings.llm_mock else "mock",
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_thb=cost_thb,
        )
    )
    db.commit()
    return text
