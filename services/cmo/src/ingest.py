"""Data ingestion & cleaning — reads every CSV/XLSX in data/raw and normalises it."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Canonical schema. Missing numeric columns are created and filled with 0.
NUMERIC_COLS = [
    "Spend",
    "Impressions",
    "Clicks",
    "Leads",
    "Conversions",
    "Revenue",
    "Foot_Traffic",
    "Flyers_Distributed",
]
REQUIRED_DIMS = ["Project", "Channel"]


class DataQualityIssue(Exception):
    """Raised when the input data cannot support a meaningful analysis."""


def _read_one(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def load_raw(raw_dir: Path) -> pd.DataFrame:
    """Read + concatenate every supported file in raw_dir into one DataFrame."""
    files = sorted(
        p for p in raw_dir.glob("*")
        if p.suffix.lower() in {".csv", ".xlsx", ".xlsm", ".xls"}
    )
    if not files:
        raise DataQualityIssue(
            f"ไม่พบไฟล์ข้อมูลใน {raw_dir} — วางไฟล์ .csv หรือ .xlsx ก่อนรัน"
        )
    frames = []
    for f in files:
        df = _read_one(f)
        df["_source_file"] = f.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Normalise columns/types and surface data-quality warnings.

    Returns (clean_df, warnings). Warnings feed the report's data-health section.
    """
    warnings: list[str] = []
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for dim in REQUIRED_DIMS:
        if dim not in df.columns:
            raise DataQualityIssue(f"ขาดคอลัมน์บังคับ: '{dim}'")
        df[dim] = df[dim].astype(str).str.strip()

    if "Campaign" not in df.columns:
        df["Campaign"] = df["Channel"]
        warnings.append("ไม่มีคอลัมน์ 'Campaign' — ใช้ชื่อ Channel แทน")

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        if df["Date"].isna().any():
            warnings.append("บาง Date แปลงไม่ได้ (รูปแบบวันที่ไม่สม่ำเสมอ)")
    else:
        warnings.append("ไม่มีคอลัมน์ 'Date' — วิเคราะห์แบบรวมช่วงเวลาไม่ได้")

    for col in NUMERIC_COLS:
        if col not in df.columns:
            df[col] = 0
            if col in ("Spend", "Conversions", "Revenue"):
                warnings.append(f"ไม่มีคอลัมน์ '{col}' — เติมค่า 0 (ตัวชี้วัดบางตัวจะเพี้ยน)")
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Drop rows with no channel/project identity
    before = len(df)
    df = df[(df["Project"] != "") & (df["Channel"] != "")]
    if len(df) < before:
        warnings.append(f"ตัดแถวที่ไม่มี Project/Channel ออก {before - len(df)} แถว")

    # Anomaly hints
    neg = df[df["Spend"] < 0]
    if not neg.empty:
        warnings.append(f"พบ Spend ติดลบ {len(neg)} แถว — ตรวจสอบ pipeline การเก็บข้อมูล")
    rev_no_spend = df[(df["Revenue"] > 0) & (df["Spend"] == 0) & (df["Channel"].str.contains("Ads", case=False, na=False))]
    if not rev_no_spend.empty:
        warnings.append(
            f"มี {len(rev_no_spend)} แถวช่องทาง Ads ที่มีรายได้แต่ Spend = 0 — อาจ track งบไม่ครบ"
        )

    return df, warnings
