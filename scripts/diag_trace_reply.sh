#!/bin/bash
# What did the seats actually reply? Call one seat directly with the same
# prompt the routine builds, and print the raw text before any parsing.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
from app import config, llm, routines, store

rid = store.get_routines()[0]["id"]
routine = store.get_routine(rid)
print("routine:", routine["task"][:70])
print("seats:", routine["seats"])

# rebuild exactly what run_routine would send
import app.routines as R
prompt = None
orig = llm.chat
seen = {}


def spy(provider, system, user, **kw):
    seen.setdefault("system", system)
    seen.setdefault("user", user)
    seen.setdefault("provider", provider)
    return {"text": "", "provider": provider, "model": "m", "ok": True}


llm.chat = spy
try:
    R.run_routine(routine)
finally:
    llm.chat = orig

print("\n--- system prompt (tail 400) ---")
print(seen["system"][-400:])
print("\n--- user prompt (tail 700) ---")
print(seen["user"][-700:])
print("\n--- does the prompt carry the schema? ---")
print("has TASK_SCHEMA:", "ตอบเป็น JSON ล้วนเท่านั้น" in seen["user"])

# now one real call to the CFO's provider
dept = routine["seats"][0]
provider = store.get_providers().get(dept, "mock")
print(f"\n--- live call: {dept} via {provider} ---")
out = llm.chat(provider, seen["system"], seen["user"], max_tokens=4096)
print("ok:", out["ok"], "| chars:", len(out["text"]))
print("raw reply (first 700):")
print(out["text"][:700])
PY
