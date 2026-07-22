#!/bin/bash
# Probe the three template repos (public API, read-only)
for r in COO_command CMO_command CFO_command; do
  echo "=== $r ==="
  curl -s "https://api.github.com/repos/minerelx168-sketch/$r" -o "/tmp/repo_$r.json"
  head -c 300 "/tmp/repo_$r.json"; echo
done
