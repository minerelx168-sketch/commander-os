"""Cross-channel performance classification — the CMO's judgement layer."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import metrics


@dataclass
class ChannelVerdict:
    project: str
    channel: str
    spend: float
    revenue: float
    roas: float
    cpa: float
    conversions: int
    verdict: str          # SCALE | CUT | KILL | WATCH | HOLD
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        # JSON-safe: NaN -> None
        for k, v in d.items():
            if isinstance(v, float) and math.isnan(v):
                d[k] = None
        return d


def classify(df: pd.DataFrame, thresholds: dict) -> list[ChannelVerdict]:
    """Assign each (project, channel) a decisive verdict against the thresholds."""
    agg = metrics.aggregate(df, by=["Project", "Channel"])
    t = thresholds
    verdicts: list[ChannelVerdict] = []

    for _, r in agg.iterrows():
        roas = r["ROAS"]
        cpa = r["CPA"]
        conv = int(r["Conversions"])
        spend = float(r["Spend"])
        reasons: list[str] = []

        low_volume = conv < t["min_conversions"] or spend < t["min_spend"]

        if low_volume:
            verdict = "WATCH"
            reasons.append(
                f"ข้อมูลยังน้อย (conv={conv}, spend={spend:,.0f}) — sample เล็ก ยังไม่ตัดสิน"
            )
        elif not math.isnan(roas) and roas < t["roas_kill"]:
            verdict = "KILL"
            reasons.append(f"ROAS {roas:.2f} < เกณฑ์หยุด {t['roas_kill']}")
            if not math.isnan(cpa) and cpa > t["cpa_ceiling"]:
                reasons.append(f"CPA {cpa:,.0f} เกินเพดาน {t['cpa_ceiling']:,.0f}")
        elif not math.isnan(cpa) and cpa > t["cpa_ceiling"]:
            verdict = "CUT"
            reasons.append(f"CPA {cpa:,.0f} เกินเพดาน {t['cpa_ceiling']:,.0f} (ROAS ยังพอไหว {roas:.2f})")
        elif not math.isnan(roas) and roas >= t["roas_scale"]:
            verdict = "SCALE"
            reasons.append(f"ROAS {roas:.2f} ≥ เกณฑ์เพิ่มงบ {t['roas_scale']} + volume พอ")
        else:
            verdict = "HOLD"
            reasons.append(f"ผลงานกลางๆ (ROAS {roas:.2f}) — คงงบ เฝ้าดูแนวโน้ม")

        verdicts.append(
            ChannelVerdict(
                project=r["Project"],
                channel=r["Channel"],
                spend=spend,
                revenue=float(r["Revenue"]),
                roas=float(roas) if not math.isnan(roas) else float("nan"),
                cpa=float(cpa) if not math.isnan(cpa) else float("nan"),
                conversions=conv,
                verdict=verdict,
                reasons=reasons,
            )
        )

    # rank: best ROAS first
    verdicts.sort(key=lambda v: (-(v.roas if not math.isnan(v.roas) else -1)))
    return verdicts


def best_and_worst(verdicts: list[ChannelVerdict]) -> dict:
    """Highlight top and bottom performer with enough volume to trust."""
    trusted = [v for v in verdicts if v.verdict != "WATCH" and not math.isnan(v.roas)]
    if not trusted:
        return {"best": None, "worst": None}
    return {
        "best": max(trusted, key=lambda v: v.roas),
        "worst": min(trusted, key=lambda v: v.roas),
    }
