#!/bin/bash
# Retry SSH to the GCP host while metadata propagates; report verbose auth detail on failure
for i in 1 2 3 4 5 6; do
  if ssh -o BatchMode=yes -o ConnectTimeout=10 commander-cloud3 'echo CONNECTED' 2>/dev/null | grep -q CONNECTED; then
    echo "SSH OK after $((i*15))s"
    exit 0
  fi
  echo "attempt $i: still denied…"
  sleep 15
done
echo "--- still failing; verbose auth trace (last 20 lines) ---"
ssh -vv -o BatchMode=yes -o ConnectTimeout=10 commander-cloud3 'echo x' 2>&1 \
  | grep -Ei 'offer|authenticat|publickey|denied|Server accepts|oslogin' | tail -20
exit 1
