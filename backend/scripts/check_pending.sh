#!/bin/bash
echo "== pending approvals =="
curl -s http://localhost:8100/api/approvals | head -c 700
echo
cd ~/commander-os/backend
unset PYTHONPATH && source .venv/bin/activate
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from sqlalchemy import text
from app.database import get_engine
with get_engine().connect() as c:
    for r in c.execute(text("SELECT id,status FROM tasks WHERE id=23")):
        print("TASK23:", r)
    for r in c.execute(text("SELECT id,status,agent FROM approvals WHERE task_id=23 ORDER BY id")):
        print("APPROVAL:", r)
EOF
