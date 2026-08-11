"""Write the CEO's search keys into hub/.env (key-scoped, no reordering)."""
import pathlib
import re

ENV = pathlib.Path("/Users/boston/commander-os/hub/.env")
NEW = {
    "SERPAPI_API_KEY": "2d2dec5553c0b2681c415919df45757c502d4ed38a6186682dce53431e34b6f0",
    "TAVILY_API_KEY": "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",
}

lines = ENV.read_text(encoding="utf-8").splitlines(keepends=True)
seen, out = set(), []
for line in lines:
    m = re.match(r"^([A-Z0-9_]+)=", line)
    key = m.group(1) if m else None
    if key in NEW:
        seen.add(key)
        out.append(f"{key}={NEW[key]}" + ("\n" if line.endswith("\n") else ""))
        continue
    out.append(line)

for key, val in NEW.items():
    if key not in seen:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"{key}={val}\n")

ENV.write_text("".join(out), encoding="utf-8")

for key in NEW:
    line = next((x.strip() for x in ENV.read_text(encoding="utf-8").splitlines()
                 if x.startswith(key + "=")), "MISSING")
    k, _, v = line.partition("=")
    print(f"  {k} = {v[:12]}…{v[-4:]} (len={len(v)})")
print(f"updated={sorted(seen)} appended={sorted(set(NEW) - seen)}")
