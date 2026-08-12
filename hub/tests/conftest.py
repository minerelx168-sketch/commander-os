import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Search keys must not leak from the developer's .env into the suite. With a
# real TAVILY/SERPAPI key present, research.backend() stops being duckduckgo and
# tests that patch _duckduckgo silently start hitting the live internet — they
# then fail (or pass) on whatever the web happens to return that day. Clearing
# the keys before app.config is imported pins every test to the keyless path,
# which is the one the fixtures actually stub.
for _key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "SERPER_API_KEY", "SERPAPI_API_KEY"):
    os.environ[_key] = ""

# Same reasoning for the hub's own API key: with HERMES_API_KEY set in .env every
# unauthenticated test call would 401. Auth is exercised deliberately in
# test_auth.py, which sets the key on config itself.
os.environ["HERMES_API_KEY"] = ""
