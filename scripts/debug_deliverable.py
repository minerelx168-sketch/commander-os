"""Reproduce the deliverable JSON-parse failure and show WHY (raw tail + stop reason)."""
import sys

sys.path.insert(0, "/Users/boston/commander-os/hub")
import httpx  # noqa: E402
from app import config, deliverable as D, report, store  # noqa: E402

sid, dept = int(sys.argv[1]), sys.argv[2]
session = store.get_consult(sid)
if session is None:
    raise SystemExit(f"consult {sid} not found")

spec = D.SPECS[dept]
system = D._author_system(spec)
user = D._grounding(session)
provider = store.get_providers().get(dept, "mock")
model = config.PROVIDERS[provider]["model"]
print(f"consult {sid} · {dept} · {provider}/{model}")
print(f"system chars={len(system)}  user chars={len(user)}")

if provider in ("anthropic", "anthropic_fable"):
    r = httpx.post("https://api.anthropic.com/v1/messages",
                   headers={"x-api-key": config.ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01"},
                   json={"model": model, "max_tokens": 8192, "system": system,
                         "messages": [{"role": "user", "content": user}]}, timeout=300)
    j = r.json()
    text = "\n".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    print(f"HTTP {r.status_code} stop_reason={j.get('stop_reason')} usage={j.get('usage')}")
elif provider == "zai":
    r = httpx.post(config.ZAI_API_URL,
                   headers={"Authorization": f"Bearer {config.ZAI_API_KEY}"},
                   json={"model": model, "max_tokens": 8192,
                         "thinking": {"type": "disabled"},
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": user}]}, timeout=300)
    j = r.json()
    ch = j["choices"][0]
    text = (ch["message"].get("content") or "")
    print(f"HTTP {r.status_code} finish_reason={ch.get('finish_reason')} usage={j.get('usage')}")
else:
    r = httpx.post(config.DEEPSEEK_API_URL,
                   headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
                   json={"model": model, "max_tokens": 8192,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": user}]}, timeout=300)
    j = r.json()
    ch = j["choices"][0]
    text = (ch["message"].get("content") or "")
    print(f"HTTP {r.status_code} finish_reason={ch.get('finish_reason')} usage={j.get('usage')}")

parsed = report._parse_json(text)
print(f"reply chars={len(text)}  parses={parsed is not None}  "
      f"has_sections={bool((parsed or {}).get('sections'))}")
print(f"starts: {text[:90]!r}")
print(f"ends:   {text[-160:]!r}")
if parsed:
    print(f"top-level keys: {list(parsed)}")
    print(f"section keys:   {list((parsed.get('sections') or {}))}")
