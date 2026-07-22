"""Orchestrator — the autonomous CMO run.

    raw data -> clean -> metrics -> classify -> budget commands -> Gemini ideas -> report

Run:  python -m src.main            (uses config paths)
      python -m src.main --raw path/to/file.csv
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import analyze, budget, command_queue, gemini_advisor, ingest, metrics, report
from .settings import load_config, resolve


def run(raw_override: str | None = None) -> dict:
    cfg = load_config()
    raw_dir = Path(raw_override).parent if raw_override else resolve(cfg["paths"]["raw_dir"])
    processed_dir = resolve(cfg["paths"]["processed_dir"])
    reports_dir = resolve(cfg["paths"]["reports_dir"])
    commands_dir = resolve(cfg["paths"]["commands_dir"])
    for d in (processed_dir, reports_dir, commands_dir):
        d.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # 1) ingest + clean
    if raw_override:
        raw = ingest._read_one(Path(raw_override))
        raw["_source_file"] = Path(raw_override).name
    else:
        raw = ingest.load_raw(raw_dir)
    clean_df, warnings = ingest.clean(raw)

    # persist cleaned + per-channel metrics
    clean_df.to_csv(processed_dir / f"clean_{run_id}.csv", index=False)
    agg = metrics.aggregate(clean_df, by=["Project", "Channel"])
    agg.to_csv(processed_dir / f"metrics_{run_id}.csv", index=False)

    # 2) classify + 3) budget
    totals = metrics.portfolio_totals(clean_df)
    verdicts = analyze.classify(clean_df, cfg["thresholds"])
    commands = budget.build_commands(verdicts, cfg["budget"])

    # 4) strategic ideas (Gemini or fallback)
    ideas, source = gemini_advisor.generate_ideas(verdicts, totals, cfg)

    # 5) persist queue + report
    command_queue.write_queue(commands, commands_dir, run_id)
    md = report.render(verdicts, commands, totals, ideas, warnings, source, run_id)
    report_path = reports_dir / f"cmo_summary_{run_id}.md"
    report_path.write_text(md, encoding="utf-8")
    (reports_dir / "latest.md").write_text(md, encoding="utf-8")

    print(md)
    print(f"\n✅ report -> {report_path}")
    print(f"✅ command queue -> {commands_dir / f'command_queue_{run_id}.json'}")

    return {
        "run_id": run_id,
        "totals": totals,
        "verdicts": [v.as_dict() for v in verdicts],
        "commands": [c.as_dict() for c in commands],
        "ideas": ideas,
        "ideas_source": source,
        "warnings": warnings,
        "report_path": str(report_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="CMO Command System — autonomous run")
    ap.add_argument("--raw", help="วิเคราะห์ไฟล์เดียวแทนทั้งโฟลเดอร์")
    ap.add_argument("--json", action="store_true", help="พิมพ์ผลลัพธ์เป็น JSON")
    args = ap.parse_args()
    result = run(args.raw)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
