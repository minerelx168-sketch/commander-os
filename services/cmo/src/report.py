"""Render the CMO Executive Command Summary (Thai) as Markdown."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .analyze import ChannelVerdict
from .budget import BudgetCommand


def _fmt(v, money=False, pct=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if pct:
        return f"{v*100:.1f}%"
    if money:
        return f"{v:,.0f}"
    return f"{v:.2f}"


def render(
    verdicts: list[ChannelVerdict],
    commands: list[BudgetCommand],
    totals: dict,
    ideas: list[dict],
    warnings: list[str],
    ideas_source: str,
    run_id: str,
) -> str:
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    A = lines.append

    A(f"# 📊 สรุปคำสั่งบริหารจาก CMO (CMO Executive Command Summary)")
    A(f"_Run `{run_id}` · {ts} · กลยุทธ์โดย: **{ideas_source.upper()}**_\n")

    # data health
    if warnings:
        A("> ⚠️ **แจ้งเตือนคุณภาพข้อมูล (Tracking pipeline)**")
        for w in warnings:
            A(f"> - {w}")
        A("")

    # ---- [สรุปภาพรวมผลงาน] ----
    A("## 1) [สรุปภาพรวมผลงาน]")
    A(
        f"- งบรวม **{_fmt(totals['total_spend'], money=True)}** · "
        f"รายได้รวม **{_fmt(totals['total_revenue'], money=True)}** · "
        f"กำไรสุทธิ **{_fmt(totals['net_profit'], money=True)}**"
    )
    A(
        f"- Blended ROAS **{_fmt(totals['blended_roas'])}** · "
        f"Blended CAC **{_fmt(totals['blended_cac'], money=True)}** · "
        f"Blended CVR **{_fmt(totals['blended_cvr'], pct=True)}**"
    )
    A("")
    A("| Project | Channel | ROAS | CPA | Conv | คำตัดสิน |")
    A("|---|---|---:|---:|---:|:--|")
    emoji = {"SCALE": "🟢", "HOLD": "🟡", "WATCH": "⚪", "CUT": "🟠", "KILL": "🔴"}
    for v in verdicts:
        A(
            f"| {v.project} | {v.channel} | {_fmt(v.roas)} | {_fmt(v.cpa, money=True)} | "
            f"{v.conversions} | {emoji.get(v.verdict,'')} {v.verdict} |"
        )
    A("")

    # ---- [การจัดการงบประมาณ] ----
    A("## 2) [การจัดการงบประมาณ] — คำสั่ง (รออนุมัติ)")
    if not commands:
        A("_ยังไม่มีคำสั่งโยกงบ — ทุกช่องทางอยู่ในเกณฑ์ HOLD/WATCH_\n")
    else:
        A("| Project | Channel | คำสั่ง | งบเดิม | งบใหม่ | Δ | เหตุผล |")
        A("|---|---|:--|---:|---:|---:|:--|")
        act_emoji = {"INCREASE": "⬆️", "DECREASE": "⬇️", "PAUSE": "⏸️"}
        for c in commands:
            A(
                f"| {c.project} | {c.channel} | {act_emoji.get(c.action,'')} {c.action} | "
                f"{_fmt(c.current_budget, money=True)} | {_fmt(c.proposed_budget, money=True)} | "
                f"{_fmt(c.delta, money=True)} ({_fmt(c.delta_pct, pct=True)}) | {c.reason} |"
            )
        released = -sum(c.delta for c in commands if c.delta < 0)
        deployed = sum(c.delta for c in commands if c.delta > 0)
        reserve = released - deployed
        A(
            f"\n**สรุปการโยกงบ:** ปลดออก **{_fmt(released, money=True)}** · "
            f"นำไปลงช่องทางชนะ **{_fmt(deployed, money=True)}** · "
            f"กันเป็นงบสำรอง/ประหยัด **{_fmt(reserve, money=True)}**"
        )
        if reserve > 1:
            A(
                f"> ℹ️ redeploy ได้ไม่หมดในรอบนี้เพราะ guardrail จำกัดการเพิ่มงบต่อช่องทางที่ "
                "max_shift — กันส่วนต่างไว้เป็นเงินสำรอง (ปรับ `max_shift_pct` เพื่ออัดเร็วขึ้น)"
            )
        A("\n> 🔒 ทุกคำสั่งสถานะ `PENDING_APPROVAL` — ต้องกดอนุมัติก่อนมีผล\n")

    # ---- [แผนผังกลยุทธ์] ----
    A("## 3) [แผนผังกลยุทธ์] — ไอเดีย/AB test สัปดาห์หน้า")
    for i, idea in enumerate(ideas, 1):
        A(f"### {i}. {idea.get('title','(ไม่มีชื่อ)')}")
        if idea.get("hypothesis"):
            A(f"- **สมมติฐาน:** {idea['hypothesis']}")
        if idea.get("action"):
            A(f"- **ลงมือ:** {idea['action']}")
        if idea.get("metric_to_watch"):
            A(f"- **วัดผลที่:** {idea['metric_to_watch']}")
        if idea.get("based_on"):
            A(f"- **อิงข้อมูล:** `{idea['based_on']}`")
        A("")

    A("---")
    A("_สร้างโดย CMO Command System — ข้อมูลอ้างอิงจริงเท่านั้น_")
    return "\n".join(lines)
