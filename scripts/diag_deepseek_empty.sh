#!/bin/bash
# DeepSeek returns 0 chars for the routine prompt. Is it the token budget
# (reasoning model spends the budget thinking) or the prompt itself?
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
from app import llm, routines, store

P = store.get_providers().get("datalyst", "mock")
print("provider:", P)
system = routines._seat_prompt("datalyst")
short = "สรุปตัวเลขสำคัญของธุรกิจตู้ดอกไม้ ยังไม่มีข้อมูลจริง"

for budget in (4096, 8192, 16384):
    out = llm.chat(P, system, short + "\n\n" + routines.ROUTINE_SCHEMA,
                   max_tokens=budget, attempts=1)
    print(f"  max_tokens={budget:6} ok={out['ok']} chars={len(out['text'])} "
          f"truncated={out.get('truncated')} :: {out['text'][:70]!r}")

print("\n-- without the schema, same budget --")
out = llm.chat(P, system, short, max_tokens=4096, attempts=1)
print(f"  ok={out['ok']} chars={len(out['text'])} :: {out['text'][:70]!r}")
PY
