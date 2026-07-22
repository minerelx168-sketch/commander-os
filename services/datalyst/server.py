"""Datalyst — Data Analyst service (Signal Layer).

No template repo was provided for the analyst, so this is a minimal service in
the same spirit as the three *_command repos: deterministic numbers from local
data + /api/summary that the hub injects into the analyst's LLM prompt.
Run: uvicorn server:app --port 8204
"""
import csv
import statistics
from pathlib import Path

from fastapi import FastAPI

app = FastAPI(title="Datalyst Command")
DATA = Path(__file__).resolve().parent / "data"


def _load_rows() -> list[dict]:
    rows = []
    for f in sorted(DATA.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            rows.extend(csv.DictReader(fh))
    return rows


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "datalyst-command"}


@app.get("/api/summary")
def summary() -> dict:
    rows = _load_rows()
    if not rows:
        return {"rows": 0, "note": "วางไฟล์ .csv ใน services/datalyst/data/ เพื่อให้วิเคราะห์"}
    numeric: dict[str, list[float]] = {}
    for row in rows:
        for k, v in row.items():
            try:
                numeric.setdefault(k, []).append(float(v))
            except (TypeError, ValueError):
                continue
    stats = {
        k: {"count": len(vs), "sum": round(sum(vs), 2),
            "mean": round(statistics.fmean(vs), 2),
            "min": min(vs), "max": max(vs)}
        for k, vs in numeric.items() if vs
    }
    return {"rows": len(rows), "columns": list(rows[0].keys()), "stats": stats}
