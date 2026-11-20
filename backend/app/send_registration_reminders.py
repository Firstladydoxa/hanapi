"""Send due incomplete-registration reminders.

Run periodically from cron/systemd (for example every 5 minutes):
    cd backend && python -m app.send_registration_reminders
"""
from app.database import SessionLocal
from app.api.auth import send_due_registration_reminders


def main() -> None:
    with SessionLocal() as db:
        count = send_due_registration_reminders(db)
    print(f"Sent {count} incomplete-registration reminder(s).")


if __name__ == "__main__":
    main()
