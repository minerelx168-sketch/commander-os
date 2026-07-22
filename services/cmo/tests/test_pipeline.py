"""Unit tests for the CMO engine: metrics, classification, budget guardrails."""
import math

import pandas as pd
import pytest

from src import analyze, budget, ingest, metrics
from src.settings import load_config


def _df():
    return pd.DataFrame(
        [
            # winner: high ROAS, enough volume
            {"Project": "P", "Channel": "Booth", "Spend": 20000, "Revenue": 300000,
             "Leads": 500, "Conversions": 150, "Impressions": 0, "Clicks": 0,
             "Foot_Traffic": 4000, "Flyers_Distributed": 0},
            # loser: ROAS < kill threshold
            {"Project": "P", "Channel": "TikTok Ads", "Spend": 30000, "Revenue": 30000,
             "Leads": 200, "Conversions": 20, "Impressions": 900000, "Clicks": 7000,
             "Foot_Traffic": 0, "Flyers_Distributed": 0},
            # tiny sample: should be WATCH not judged
            {"Project": "P", "Channel": "Flyer", "Spend": 1000, "Revenue": 5000,
             "Leads": 20, "Conversions": 2, "Impressions": 0, "Clicks": 0,
             "Foot_Traffic": 0, "Flyers_Distributed": 3000},
        ]
    )


def test_metrics_basic():
    m = metrics.add_metrics(_df())
    booth = m[m.Channel == "Booth"].iloc[0]
    assert booth["ROAS"] == pytest.approx(15.0)
    assert booth["CAC"] == pytest.approx(20000 / 150)
    assert booth["Booth_CVR"] == pytest.approx(150 / 4000)


def test_safe_div_no_zero_crash():
    m = metrics.add_metrics(
        pd.DataFrame([{"Project": "X", "Channel": "Meta Ads", "Spend": 0, "Revenue": 0,
                       "Leads": 0, "Conversions": 0, "Impressions": 0, "Clicks": 0,
                       "Foot_Traffic": 0, "Flyers_Distributed": 0}])
    )
    assert math.isnan(m.iloc[0]["ROAS"])  # 0/0 -> NaN, not a crash


def test_classification_verdicts():
    cfg = load_config()
    verdicts = {v.channel: v.verdict for v in analyze.classify(_df(), cfg["thresholds"])}
    assert verdicts["Booth"] == "SCALE"
    assert verdicts["TikTok Ads"] == "KILL"
    assert verdicts["Flyer"] == "WATCH"  # low volume -> not judged


def test_budget_guardrails():
    cfg = load_config()
    verdicts = analyze.classify(_df(), cfg["thresholds"])
    cmds = budget.build_commands(verdicts, cfg["budget"])
    floor = cfg["budget"]["min_floor"]
    max_shift = cfg["budget"]["max_shift_pct"]
    for c in cmds:
        assert c.proposed_budget >= floor - 1e-6            # never below floor
        if c.action == "INCREASE":
            assert c.delta <= c.current_budget * max_shift + 1e-6  # cap respected
        assert c.status == "PENDING_APPROVAL"               # human gate


def test_clean_flags_missing_columns():
    df = pd.DataFrame([{"Project": "P", "Channel": "Meta Ads", "Revenue": 100}])
    clean, warns = ingest.clean(df)
    assert "Spend" in clean.columns
    assert any("Spend" in w for w in warns)


def test_ingest_empty_dir_raises(tmp_path):
    with pytest.raises(ingest.DataQualityIssue):
        ingest.load_raw(tmp_path)
