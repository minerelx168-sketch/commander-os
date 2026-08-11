"""Reset the seat->agent map to config.DEFAULT_PROVIDERS.

The stored map is the CEO's live choice and is normally left alone, but a stale
'anthropic' on the CFO seat put two seats on the same vendor — which defeats the
whole point of a Crucible board. Consults and decisions are untouched.
"""
import json
import pathlib
import sys

HUB = pathlib.Path("/Users/boston/commander-os/hub")
sys.path.insert(0, str(HUB))
from app import config, depts  # noqa: E402

f = HUB / "memory" / "hub_store.json"
data = json.loads(f.read_text(encoding="utf-8"))
before = dict(data.get("providers") or {})
data["providers"] = {d: config.DEFAULT_PROVIDERS.get(d, "mock") for d in config.DEPTS}
f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

print("seat          before           ->  after            model                    vendor")
for dept in config.DEPTS:
    now = data["providers"][dept]
    print(f"  {dept:11} {before.get(dept, '(none)'):16} ->  {now:16} "
          f"{config.PROVIDERS[now]['model']:24} {depts.vendor_of(now)}")

vendors = {depts.vendor_of(p) for p in data["providers"].values()}
models = {config.PROVIDERS[p]["model"] for p in data["providers"].values()}
print(f"\ndistinct models: {len(models)}/{len(config.DEPTS)}  "
      f"distinct vendors: {len(vendors)} -> {sorted(vendors)}")
print(f"consults preserved: {len(data.get('consults') or [])}, "
      f"decisions preserved: {len(data.get('decisions') or [])}")
