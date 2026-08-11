#!/bin/bash
# Add SSH connection multiplexing for commander-cloud3 (GCP throttles repeated handshakes)
set -e
CFG="$HOME/.ssh/config"
grep -q 'ControlMaster auto' "$CFG" || python3 - "$CFG" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace(
    "Host commander-cloud3\n  HostName 34.75.96.28\n  User ubuntu\n  Port 22\n"
    "  IdentityFile ~/.ssh/hermes_cloud3\n  StrictHostKeyChecking accept-new\n"
    "  ServerAliveInterval 30\n",
    "Host commander-cloud3\n  HostName 34.75.96.28\n  User ubuntu\n  Port 22\n"
    "  IdentityFile ~/.ssh/hermes_cloud3\n  IdentitiesOnly yes\n"
    "  StrictHostKeyChecking accept-new\n  ServerAliveInterval 30\n"
    "  ControlMaster auto\n  ControlPath ~/.ssh/cm-%r@%h:%p\n  ControlPersist 10m\n"
    "  ConnectionAttempts 3\n",
)
open(p, "w").write(s)
PY
chmod 600 "$CFG"
ssh -G commander-cloud3 | grep -E 'controlmaster|controlpath|identitiesonly|connectionattempts'
