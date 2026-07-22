"""Budget reallocation engine with guardrails — turns verdicts into concrete commands.

Strategy (per project, budget-neutral by default):
  * KILL / CUT channels release budget (bounded by max_shift_pct, never below floor).
  * SCALE channels receive that released budget, weighted by their ROAS.
Every command lands in the queue as PENDING_APPROVAL — no money moves without a human.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .analyze import ChannelVerdict


@dataclass
class BudgetCommand:
    project: str
    channel: str
    action: str            # DECREASE | PAUSE | INCREASE
    current_budget: float
    proposed_budget: float
    delta: float
    delta_pct: float
    reason: str
    status: str = "PENDING_APPROVAL"

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def build_commands(verdicts: list[ChannelVerdict], budget_cfg: dict) -> list[BudgetCommand]:
    """Produce budget-neutral reallocation commands per project, respecting guardrails."""
    max_shift = budget_cfg["max_shift_pct"]
    floor = budget_cfg["min_floor"]
    neutral = budget_cfg.get("budget_neutral", True)

    commands: list[BudgetCommand] = []

    projects = sorted({v.project for v in verdicts})
    for project in projects:
        pv = [v for v in verdicts if v.project == project]
        released = 0.0
        cut_cmds: list[BudgetCommand] = []

        # 1) Release budget from losers
        for v in pv:
            if v.verdict not in ("KILL", "CUT"):
                continue
            if v.verdict == "KILL":
                # pause hard, but keep a learning floor
                proposed = min(v.spend, floor)
                action = "PAUSE"
            else:  # CUT
                proposed = max(floor, v.spend * (1 - max_shift))
                action = "DECREASE"
            delta = proposed - v.spend
            if delta >= 0:
                continue  # nothing to release
            released += -delta
            cut_cmds.append(
                BudgetCommand(
                    project=project,
                    channel=v.channel,
                    action=action,
                    current_budget=round(v.spend, 2),
                    proposed_budget=round(proposed, 2),
                    delta=round(delta, 2),
                    delta_pct=round(delta / v.spend, 4) if v.spend else 0.0,
                    reason="; ".join(v.reasons),
                )
            )

        commands.extend(cut_cmds)

        # 2) Deploy released budget into scalers, weighted by ROAS
        scalers = [v for v in pv if v.verdict == "SCALE"]
        if not scalers:
            continue

        pool = released if neutral else max(released, sum(s.spend * max_shift for s in scalers))
        weights = {s.channel: (s.roas if not math.isnan(s.roas) else 0.0) for s in scalers}
        wsum = sum(weights.values()) or 1.0

        for s in scalers:
            share = pool * (weights[s.channel] / wsum)
            cap = s.spend * max_shift  # never scale a single channel by more than max_shift
            add = min(share, cap)
            if add <= 0:
                continue
            proposed = s.spend + add
            commands.append(
                BudgetCommand(
                    project=project,
                    channel=s.channel,
                    action="INCREASE",
                    current_budget=round(s.spend, 2),
                    proposed_budget=round(proposed, 2),
                    delta=round(add, 2),
                    delta_pct=round(add / s.spend, 4) if s.spend else 0.0,
                    reason="; ".join(s.reasons)
                    + f"; รับงบที่โยกมา (สัดส่วนตาม ROAS {s.roas:.2f})",
                )
            )

    return commands
