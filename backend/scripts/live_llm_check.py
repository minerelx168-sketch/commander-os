"""Quick live check: real Gemini call through our llm service + cost tracking."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_sessionmaker
from app.services import llm


def main() -> None:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        out = llm.complete(
            db,
            agent="ceo",
            purpose="live_check",
            system="ตอบสั้นๆ ภาษาไทย",
            user="ทดสอบระบบ ตอบว่า 'ระบบพร้อม' ถ้าได้ยิน",
        )
    print("GEMINI RESPONSE:", out[:200])


if __name__ == "__main__":
    main()
