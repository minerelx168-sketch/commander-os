"""Check task 23 status + which models each agent used."""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from app.database import get_engine

engine = get_engine()

with engine.connect() as c:
    for row in c.execute(text("SELECT id,status,title FROM tasks WHERE id=23")):
        print("TASK:", row)
    print("--- cost entries (models used) ---")
    for row in c.execute(text(
        "SELECT agent,model,input_tokens,output_tokens FROM cost_entries WHERE task_id=23 ORDER BY id"
    )):
        print(row)
