"""Load configuration from config/config.yaml with sane fallbacks."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"

_DEFAULTS: dict[str, Any] = {
    "gemini": {"model": "gemini-2.0-flash", "temperature": 0.4},
    "thresholds": {
        "roas_kill": 1.5,
        "roas_scale": 3.0,
        "cpa_ceiling": 400,
        "min_conversions": 10,
        "min_spend": 3000,
    },
    "budget": {
        "max_shift_pct": 0.30,
        "min_floor": 2000,
        "budget_neutral": True,
        "require_human_approval": True,
    },
    "paths": {
        "raw_dir": "data/raw",
        "processed_dir": "data/processed",
        "reports_dir": "output/reports",
        "commands_dir": "output/commands",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    """Return merged config (file over defaults). Never raises on a missing file."""
    cfg = _DEFAULTS
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        cfg = _deep_merge(_DEFAULTS, loaded)
    # env overrides
    if os.getenv("GEMINI_MODEL"):
        cfg["gemini"]["model"] = os.environ["GEMINI_MODEL"]
    return cfg


def resolve(path_str: str) -> Path:
    """Resolve a config-relative path against the project root."""
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p
