"""Ping every LLM provider through the hub's own adapter and report the real error."""
import sys, time
sys.path.insert(0, "/Users/boston/commander-os/hub")
from app import config, llm  # noqa: E402

print("=== keys loaded ===")
for name, val in [("ANTHROPIC", config.ANTHROPIC_API_KEY), ("GOOGLE", config.GOOGLE_API_KEY),
                  ("MANUS", config.MANUS_API_KEY), ("ZAI", config.ZAI_API_KEY)]:
    print(f"  {name:10} {'SET len=%d' % len(val) if val else 'MISSING'}")
print(f"  MANUS_API_URL = {config.MANUS_API_URL}")
print(f"  ZAI_API_URL   = {config.ZAI_API_URL}")
print(f"  ZAI_MODEL     = {config.PROVIDERS['zai']['model']}")

print("\n=== live ping (say OK) ===")
for p in ["anthropic", "gemini", "zai", "manus"]:
    if p == "manus":
        print("  manus     SKIPPED (task API, up to 280s)")
        continue
    t0 = time.monotonic()
    res = llm.chat(p, "Reply with exactly: OK", "ping")
    dt = time.monotonic() - t0
    print(f"  {p:10} ok={res['ok']} model={res['model']} {dt:.1f}s -> {res['text'][:180]!r}")
