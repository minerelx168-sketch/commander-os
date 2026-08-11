"""Prove the search backends and every seat's agent answer for real."""
import sys
import time

sys.path.insert(0, "/Users/boston/commander-os/hub")
from app import config, depts, llm, research, store  # noqa: E402

print("=== search backends (live) ===")
print(f"  active backend: {research.backend()} ({research.backend_label()})")
for name in ("tavily", "serpapi", "brave", "serper"):
    key = {"tavily": config.TAVILY_API_KEY, "serpapi": config.SERPAPI_API_KEY,
           "brave": config.BRAVE_API_KEY, "serper": config.SERPER_API_KEY}[name]
    if not key:
        print(f"  {name:9} — ไม่มี key")
        continue
    fn = getattr(research, research._BACKENDS[name])
    t0 = time.monotonic()
    try:
        hits = fn("ตลาดดอกไม้ออนไลน์ ประเทศไทย มูลค่า", 3)
        dt = time.monotonic() - t0
        print(f"  {name:9} ok  {dt:4.1f}s  hits={len(hits)}")
        for h in hits[:2]:
            print(f"              - {h.get('title', '')[:58]}")
            print(f"                {h.get('url', '')[:74]}")
    except Exception as e:  # noqa: BLE001
        print(f"  {name:9} FAILED after {time.monotonic() - t0:.1f}s: {type(e).__name__}: {e}")

print("\n=== every seat on its assigned agent (live) ===")
assigned = store.get_providers()
for dept in config.DEPTS:
    prov = assigned.get(dept, "mock")
    model = config.PROVIDERS[prov]["model"]
    t0 = time.monotonic()
    out = llm.chat(prov, "ตอบสั้นที่สุด", "ตอบว่า OK เท่านั้น", attempts=1)
    dt = time.monotonic() - t0
    status = "ok " if out["ok"] else "ERR"
    print(f"  {config.DEPTS[dept]['name']:14} {depts.vendor_of(prov):10} {model:24} "
          f"{status} {dt:4.1f}s  {str(out['text'])[:40].strip()}")

div = depts.model_diversity()
print(f"\ndistinct labs: {div['distinct']} · shared: {div['shared_vendors']}")
print(f"warning: {div['warning']}")
