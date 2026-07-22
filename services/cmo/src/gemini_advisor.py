"""Gemini-powered strategic ideation — grounded strictly in the analysed data.

Falls back to a deterministic, data-driven rule engine when GEMINI_API_KEY is absent,
so the pipeline always produces ideas and never hard-fails in CI.
"""
from __future__ import annotations

import json
import os
import textwrap

from .analyze import ChannelVerdict

SYSTEM_PREAMBLE = textwrap.dedent(
    """
    คุณคือ AI Chief Marketing Officer ที่ตัดสินใจด้วยข้อมูล (data-driven) และเด็ดขาด
    หน้าที่: เสนอไอเดียการตลาด/แผน A/B test 2-3 ข้อสำหรับสัปดาห์ถัดไป
    กฎเหล็ก:
      - ทุกไอเดียต้องอ้างอิงตัวเลขจากข้อมูลที่ให้เท่านั้น ห้ามแนะนำแบบกว้างๆ ทั่วไป
      - ระบุช่องทาง/โปรเจค/ตัวเลขที่ใช้ประกอบเหตุผลให้ชัด
      - เน้นการอุดช่องโหว่ระหว่างช่องทาง (เช่น booth ดี แต่ Meta แย่ -> retargeting)
    ตอบเป็น JSON array ของ object: {"title","hypothesis","action","metric_to_watch","based_on"}
    """
).strip()


def _data_brief(verdicts: list[ChannelVerdict], totals: dict) -> str:
    rows = [
        {
            "project": v.project,
            "channel": v.channel,
            "roas": round(v.roas, 2) if v.roas == v.roas else None,  # NaN check
            "cpa": round(v.cpa, 0) if v.cpa == v.cpa else None,
            "conversions": v.conversions,
            "verdict": v.verdict,
        }
        for v in verdicts
    ]
    return json.dumps(
        {"portfolio": totals, "channels": rows}, ensure_ascii=False, indent=2
    )


def _fallback_ideas(verdicts: list[ChannelVerdict]) -> list[dict]:
    """Deterministic, data-grounded ideas when no LLM is available."""
    ideas: list[dict] = []
    by_project: dict[str, list[ChannelVerdict]] = {}
    for v in verdicts:
        by_project.setdefault(v.project, []).append(v)

    for project, vs in by_project.items():
        booth = next((v for v in vs if v.channel.lower() == "booth" and v.verdict == "SCALE"), None)
        meta = next((v for v in vs if "meta" in v.channel.lower()), None)
        tiktok = next((v for v in vs if "tiktok" in v.channel.lower()), None)

        # Gap-filling: strong booth, weak Meta -> retargeting
        if booth and meta and (meta.verdict in ("KILL", "CUT", "HOLD")):
            ideas.append({
                "title": f"[{project}] Retarget ฐานลูกค้าบูธเข้า Meta",
                "hypothesis": f"Booth มี ROAS {booth.roas:.1f} แต่ Meta อ่อน (ROAS {meta.roas:.1f}) "
                              "การยิง retargeting ไปยังคนที่เก็บ lead จากบูธน่าจะดัน ROAS ของ Meta ขึ้น",
                "action": "อัปโหลด custom audience จาก lead หน้าบูธเข้า Meta แล้วยิง retargeting แยกจาก prospecting",
                "metric_to_watch": "ROAS ของ Meta retargeting vs prospecting",
                "based_on": f"Booth ROAS={booth.roas:.2f}, Meta ROAS={meta.roas:.2f}",
            })

        # High-CPA TikTok -> creative A/B test
        if tiktok and tiktok.verdict in ("KILL", "CUT"):
            ideas.append({
                "title": f"[{project}] A/B test creative TikTok ลด CPA",
                "hypothesis": f"TikTok CPA สูง ({tiktok.cpa:,.0f}) เพราะ creative ไม่ตรงกลุ่ม — "
                              "hook 3 วินาทีแรกใหม่น่าจะลด CPA",
                "action": "รัน 2 creative: (A) UGC รีวิวจริง vs (B) demo สินค้า งบเท่ากัน 3 วัน",
                "metric_to_watch": "CPA และ hold rate 3 วินาที",
                "based_on": f"TikTok CPA={tiktok.cpa:,.0f}, verdict={tiktok.verdict}",
            })

    # Always give at least one portfolio-level idea grounded in the best channel
    scalers = [v for v in verdicts if v.verdict == "SCALE"]
    if scalers:
        top = max(scalers, key=lambda v: v.roas)
        ideas.append({
            "title": f"อัดงบช่องทางชนะ: {top.project}/{top.channel}",
            "hypothesis": f"{top.channel} ทำ ROAS {top.roas:.2f} สูงสุดในพอร์ต — เพิ่ม budget แบบ step 20% "
                          "แล้ววัดว่า ROAS ยังทรงตัวก่อนอัดต่อ",
            "action": f"เพิ่มงบ {top.channel} ทีละ 20% ทุก 3 วัน จนกว่า ROAS จะเริ่มถดถอย",
            "metric_to_watch": "marginal ROAS ต่อการเพิ่มงบแต่ละ step",
            "based_on": f"{top.channel} ROAS={top.roas:.2f} (สูงสุดในพอร์ต)",
        })

    return ideas[:3] if ideas else [{
        "title": "เก็บข้อมูลเพิ่มก่อนออกกลยุทธ์",
        "hypothesis": "ข้อมูลยังไม่พอให้ตัดสินเชิงกลยุทธ์",
        "action": "รันแต่ละช่องทางต่อจน conversions ต่อช่องทาง ≥ 10 แล้วประเมินใหม่",
        "metric_to_watch": "conversions ต่อช่องทาง",
        "based_on": "sample เล็กในทุกช่องทาง",
    }]


def generate_ideas(verdicts: list[ChannelVerdict], totals: dict, cfg: dict) -> tuple[list[dict], str]:
    """Return (ideas, source) where source is 'gemini' or 'fallback'."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _fallback_ideas(verdicts), "fallback"

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            cfg["gemini"]["model"],
            system_instruction=SYSTEM_PREAMBLE,
        )
        prompt = (
            "ข้อมูลผลการตลาดล่าสุด (JSON):\n"
            + _data_brief(verdicts, totals)
            + "\n\nเสนอ 2-3 ไอเดีย/AB test ตามกฎ ตอบเป็น JSON array เท่านั้น"
        )
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": cfg["gemini"].get("temperature", 0.4),
                "response_mime_type": "application/json",
            },
        )
        ideas = json.loads(resp.text)
        if isinstance(ideas, dict):
            ideas = ideas.get("ideas", [ideas])
        return ideas, "gemini"
    except Exception as exc:  # network, quota, parse — degrade gracefully
        ideas = _fallback_ideas(verdicts)
        ideas.insert(0, {
            "title": "⚠️ Gemini ใช้งานไม่ได้ — ใช้ fallback engine",
            "hypothesis": f"เหตุผล: {exc}",
            "action": "ตรวจ GEMINI_API_KEY / โควต้า / ชื่อ model ใน config",
            "metric_to_watch": "-",
            "based_on": "system",
        })
        return ideas, "fallback"
