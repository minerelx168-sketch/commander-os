"""Daily report job — run via cron/launchd at 09:00: python -m app.jobs.daily_report"""
from ..database import get_sessionmaker
from ..routers.reports import build_daily_report
from ..services.telegram_bot import send_text


def main() -> None:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        report = build_daily_report(db)
    send_text(report)
    print(report)


if __name__ == "__main__":
    main()
