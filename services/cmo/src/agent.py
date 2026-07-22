"""CMO agent — the conversational 'Market Voice' layer.

Wraps the analysis engine as a chat interface: you message the CMO, it grounds every
answer in the latest run's real numbers (via Gemini, with a deterministic fallback).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import analyze, budget, gemini_advisor, ingest, metrics
from .settings import load_config, resolve

AGENT_CARD = {
    "name": "CMO",
    "role": "Market Voice",
    "channel": "#cmo-channel",
    "layer": "Marketing Command Layer",
    "status": "working",
}

_SYSTEM = (
    "คุณคือ AI CMO (Market Voice) ในระบบ Agentic OS ตอบสั้น กระชับ เด็ดขาด "
    "อ้างอิงตัวเลขจากบริบทข้อมูลที่ให้เท่านั้น ถ้าไม่มีข้อมูลให้บอกตรงๆ ว่าต้องเก็บ data เพิ่ม "
    "ตอบเป็นภาษาไทย"
)


def _live_context() -> dict:
    """Build a compact snapshot of the current portfolio for grounding."""
    cfg = load_config()
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    try:
        raw = ingest.load_raw(raw_dir)
        clean_df, _ = ingest.clean(raw)
    except ingest.DataQualityIssue as e:
        return {"error": str(e)}
    totals = metrics.portfolio_totals(clean_df)
    verdicts = analyze.classify(clean_df, cfg["thresholds"])
    commands = budget.build_commands(verdicts, cfg["budget"])
    return {
        "totals": totals,
        "channels": [v.as_dict() for v in verdicts],
        "pending_commands": [c.as_dict() for c in commands],
    }


def _fallback_reply(message: str, ctx: dict) -> str:
    if "error" in ctx:
        return f"ยังวิเคราะห์ไม่ได้ครับ: {ctx['error']}"
    t = ctx["totals"]
    top = ctx["channels"][0] if ctx["channels"] else None
    worst = ctx["channels"][-1] if ctx["channels"] else None
    lines = [
        "(fallback — ไม่มี GEMINI_API_KEY จึงสรุปจากตัวเลขตรงๆ)",
        f"พอร์ตรวม: ROAS {t['blended_roas']:.2f}, กำไรสุทธิ {t['net_profit']:,.0f}",
    ]
    if top:
        lines.append(f"ดีสุด: {top['project']}/{top['channel']} ROAS {top['roas']:.2f} → {top['verdict']}")
    if worst:
        lines.append(f"แย่สุด: {worst['project']}/{worst['channel']} ROAS {worst['roas']:.2f} → {worst['verdict']}")
    lines.append(f"คำสั่งงบรออนุมัติ: {len(ctx['pending_commands'])} รายการ")
    return "\n".join(lines)


def chat(message: str) -> dict:
    """Return {'reply', 'source', 'context'} for a single user message."""
    ctx = _live_context()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return {"reply": _fallback_reply(message, ctx), "source": "fallback", "context": ctx}

    try:
        import google.generativeai as genai

        cfg = load_config()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(cfg["gemini"]["model"], system_instruction=_SYSTEM)
        prompt = (
            "บริบทข้อมูลพอร์ตล่าสุด (JSON):\n"
            + json.dumps(ctx, ensure_ascii=False, default=str)
            + f"\n\nคำถาม/คำสั่งจากผู้บริหาร: {message}"
        )
        resp = model.generate_content(
            prompt, generation_config={"temperature": cfg["gemini"].get("temperature", 0.4)}
        )
        return {"reply": resp.text, "source": "gemini", "context": ctx}
    except Exception as exc:
        reply = _fallback_reply(message, ctx) + f"\n\n⚠️ Gemini error: {exc}"
        return {"reply": reply, "source": "fallback", "context": ctx}


if __name__ == "__main__":
    import sys

    msg = " ".join(sys.argv[1:]) or "สรุปสถานะพอร์ตให้หน่อย"
    out = chat(msg)
    print(f"[{AGENT_CARD['name']} · {out['source']}]\n{out['reply']}")
