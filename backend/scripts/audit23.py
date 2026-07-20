import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from app.database import get_engine

with get_engine().connect() as c:
    print("--- audit_log task 23 ---")
    for r in c.execute(text(
        "SELECT id,agent,event,substr(detail::text,1,120) FROM audit_log "
        "WHERE task_id=23 ORDER BY id"
    )):
        print(r)
