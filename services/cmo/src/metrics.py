"""Cross-channel marketing metrics: CAC, ROAS, CVR, CPA, CPL + offline booth conversion."""
from __future__ import annotations

import numpy as np
import pandas as pd

# Channels treated as offline (no impressions/clicks; foot-traffic driven)
OFFLINE_CHANNELS = {"booth", "flyer", "event", "exhibition"}


def _safe_div(a, b):
    """Element-wise divide that returns NaN instead of inf/0-division noise."""
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return np.where((b == 0) | b.isna(), np.nan, a / b)


def is_offline(channel: str) -> bool:
    return str(channel).strip().lower() in OFFLINE_CHANNELS


def aggregate(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Sum raw counts grouped by `by`, then derive metrics on the aggregate."""
    grouped = (
        df.groupby(by, as_index=False)[
            [
                "Spend",
                "Impressions",
                "Clicks",
                "Leads",
                "Conversions",
                "Revenue",
                "Foot_Traffic",
                "Flyers_Distributed",
            ]
        ].sum()
    )
    return add_metrics(grouped)


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Attach derived KPI columns to an already-aggregated frame."""
    out = df.copy()

    # ROAS = Revenue / Spend
    out["ROAS"] = _safe_div(out["Revenue"], out["Spend"])
    # CAC / CPA = Spend per acquired customer (conversion)
    out["CAC"] = _safe_div(out["Spend"], out["Conversions"])
    out["CPA"] = out["CAC"]
    # CPL = Spend per lead
    out["CPL"] = _safe_div(out["Spend"], out["Leads"])
    # Lead -> customer conversion rate
    out["CVR"] = _safe_div(out["Conversions"], out["Leads"])
    # Click-through where impressions exist
    out["CTR"] = _safe_div(out["Clicks"], out["Impressions"])
    # Revenue per lead — quality proxy
    out["Rev_per_Lead"] = _safe_div(out["Revenue"], out["Leads"])
    # Profit (revenue net of spend) and margin
    out["Profit"] = out["Revenue"] - out["Spend"]
    out["Margin"] = _safe_div(out["Profit"], out["Revenue"])

    # Offline-specific: booth walk-in -> customer conversion
    if "Channel" in out.columns:
        offline_mask = out["Channel"].map(is_offline)
        out["Booth_CVR"] = np.where(
            offline_mask, _safe_div(out["Conversions"], out["Foot_Traffic"]), np.nan
        )

    return out.round(4)


def portfolio_totals(df: pd.DataFrame) -> dict:
    """Top-line rollup across the whole dataset."""
    spend = df["Spend"].sum()
    rev = df["Revenue"].sum()
    conv = df["Conversions"].sum()
    leads = df["Leads"].sum()
    return {
        "total_spend": float(spend),
        "total_revenue": float(rev),
        "total_conversions": int(conv),
        "total_leads": int(leads),
        "blended_roas": float(rev / spend) if spend else float("nan"),
        "blended_cac": float(spend / conv) if conv else float("nan"),
        "blended_cvr": float(conv / leads) if leads else float("nan"),
        "net_profit": float(rev - spend),
    }
