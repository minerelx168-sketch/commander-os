#!/bin/bash
# Start the whole Commander Hub stack (hub + 4 dept services).
# Services are detached with nohup+setsid so they SURVIVE the parent shell exiting.
R="$HOME/commander-os"
unset PYTHONPATH
# hub/.env is the source of truth for model pins. A stale export in the calling
# shell (e.g. ZAI_MODEL from a debugging session) would otherwise win over the
# file, because load_dotenv() never overrides an existing environment variable.
unset ZAI_MODEL GEMINI_MODEL ANTHROPIC_MODEL ANTHROPIC_FABLE_MODEL \
      DEEPSEEK_MODEL MANUS_MODEL
mkdir -p "$R/logs"

# setsid isn't on macOS by default — emulate detachment with nohup in a subshell
spawn() { # name  dir  cmd...
  local name=$1 dir=$2; shift 2
  if pgrep -f "commander-os-$name" >/dev/null 2>&1; then
    echo "skip $name (already running)"; return
  fi
  ( cd "$dir" || exit 1
    COMMANDER_SVC="commander-os-$name" nohup "$@" >>"$R/logs/$name.log" 2>&1 &
    echo $! > "$R/logs/$name.pid"
    disown 2>/dev/null ) &
  sleep 0.3
  echo "started $name (pid $(cat "$R/logs/$name.pid" 2>/dev/null))"
}

# -sTCP:LISTEN matters: a browser tab holding a CLOSE_WAIT socket on the port
# is not a server, but an unfiltered lsof counts it and start_all then skips
# the spawn, leaving the stack silently down.
port_busy() { lsof -ti tcp:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# The hub runs on the Hermes venv (HUB_PY overridable); dept services keep
# their own interpreters. Hermes' PYTHONPATH is deliberately NOT unset for the
# hub — that venv IS the target environment.
HUB_PY="${HUB_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}"
[ -x "$HUB_PY" ] || HUB_PY="$R/hub/.venv/bin/python"

port_busy 8201 || spawn cmo      "$R/services/cmo"      "$R/services/cmo/.venv/bin/uvicorn" src.dashboard:app --host 0.0.0.0 --port 8201
port_busy 8202 || spawn coo      "$R/services/coo"      env PORT=8202 node src/server.js
port_busy 8203 || spawn cfo      "$R/services/cfo"      env PORT=8203 node server.js
port_busy 8204 || spawn datalyst "$R/services/datalyst" "$R/hub/.venv/bin/uvicorn" server:app --host 0.0.0.0 --port 8204
# the evidence desk imports the hub's research stack, so it runs on the hub's
# interpreter rather than a venv of its own
port_busy 8205 || spawn researcher "$R/services/researcher" "$HUB_PY" -m uvicorn server:app --host 0.0.0.0 --port 8205
port_busy 8100 || spawn hub      "$R/hub"               "$HUB_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8100

echo "waiting for services..."
# one list, used for both the readiness wait and the final report — the two
# drifted apart when the evidence desk was added
PORTS="8100 8201 8202 8203 8204 8205"
TOTAL=$(echo $PORTS | wc -w | tr -d ' ')
for i in $(seq 1 20); do
  ok=0
  for p in $PORTS; do port_busy "$p" && ok=$((ok+1)); done
  [ "$ok" -eq "$TOTAL" ] && break
  sleep 1
done

for p in $PORTS; do
  printf "port %s: " "$p"
  curl -s -m 4 -o /dev/null -w '%{http_code}\n' "http://localhost:$p/" || echo down
done
echo "Commander Hub: http://localhost:8100"
