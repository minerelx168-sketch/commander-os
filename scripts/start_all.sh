#!/bin/bash
# Start the whole Commander Hub stack (hub + 4 dept services)
set -e
R="$HOME/commander-os"
unset PYTHONPATH

start() { # name, dir, cmd...
  local name=$1; shift
  local dir=$1; shift
  if ! curl -s -m 2 -o /dev/null "$2" 2>/dev/null; then :; fi
  (cd "$dir" && "$@" >> "$R/logs/$name.log" 2>&1 &)
  echo "started $name"
}

mkdir -p "$R/logs"
(cd "$R/services/cmo" && .venv/bin/uvicorn src.dashboard:app --host 0.0.0.0 --port 8201 >> "$R/logs/cmo.log" 2>&1 &)
(cd "$R/services/coo" && PORT=8202 node src/server.js >> "$R/logs/coo.log" 2>&1 &)
(cd "$R/services/cfo" && PORT=8203 node server.js >> "$R/logs/cfo.log" 2>&1 &)
(cd "$R/services/datalyst" && "$R/hub/.venv/bin/uvicorn" server:app --host 0.0.0.0 --port 8204 >> "$R/logs/datalyst.log" 2>&1 &)
(cd "$R/hub" && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 >> "$R/logs/hub.log" 2>&1 &)
sleep 5
for p in 8100 8201 8202 8203 8204; do
  printf "port %s: " "$p"
  curl -s -m 4 -o /dev/null -w '%{http_code}\n' "http://localhost:$p/" || echo down
done
echo "Commander Hub: http://localhost:8100"
