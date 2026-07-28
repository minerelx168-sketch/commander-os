#!/bin/bash
# Start the whole Commander Hub stack (hub + 4 dept services).
# Services are detached with nohup+setsid so they SURVIVE the parent shell exiting.
R="$HOME/commander-os"
unset PYTHONPATH
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

port_busy() { lsof -ti tcp:"$1" >/dev/null 2>&1; }

port_busy 8201 || spawn cmo      "$R/services/cmo"      "$R/services/cmo/.venv/bin/uvicorn" src.dashboard:app --host 0.0.0.0 --port 8201
port_busy 8202 || spawn coo      "$R/services/coo"      env PORT=8202 node src/server.js
port_busy 8203 || spawn cfo      "$R/services/cfo"      env PORT=8203 node server.js
port_busy 8204 || spawn datalyst "$R/services/datalyst" "$R/hub/.venv/bin/uvicorn" server:app --host 0.0.0.0 --port 8204
port_busy 8100 || spawn hub      "$R/hub"               "$R/hub/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8100

echo "waiting for services..."
for i in $(seq 1 20); do
  ok=0
  for p in 8100 8201 8202 8203 8204; do port_busy "$p" && ok=$((ok+1)); done
  [ "$ok" -eq 5 ] && break
  sleep 1
done

for p in 8100 8201 8202 8203 8204; do
  printf "port %s: " "$p"
  curl -s -m 4 -o /dev/null -w '%{http_code}\n' "http://localhost:$p/" || echo down
done
echo "Commander Hub: http://localhost:8100"
