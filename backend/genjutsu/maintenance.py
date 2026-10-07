"""Explicit operator commands; never prints stored credentials or passwords."""

import argparse
import getpass
from datetime import timedelta

from argon2 import PasswordHasher
from sqlalchemy import delete, select

from .config import get_settings
from .db import Database, LoginAttempt, Session, User, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["prune-sessions", "reset-password", "prune-orphans", "check-backup"],
    )
    parser.add_argument("--email")
    args = parser.parse_args()
    settings = get_settings()
    database = Database(settings)
    with database.session.begin() as db:
        if args.command == "check-backup":
            from .db import Job

            active = db.scalar(
                select(Job.id).where(
                    Job.status.in_(["QUEUED", "RUNNING", "NEEDS_REVIEW"])
                )
            )
            if active:
                raise SystemExit(
                    "Active or unresolved jobs exist; finish or reconcile them before an offline backup."
                )
            print("No active or unresolved generation jobs.")
        elif args.command == "prune-sessions":
            db.execute(delete(Session).where(Session.expires < now()))
            db.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.since < now() - timedelta(days=1)
                )
            )
            print("Expired authentication records removed.")
        elif args.command == "prune-orphans":
            import time

            from .db import Asset

            ids = set(db.scalars(select(Asset.id)))
            removed = 0
            for file in (settings.data_dir / "assets").glob("*"):
                if (
                    file.is_file()
                    and file.name not in ids
                    and file.stat().st_mtime < time.time() - 86400
                ):
                    file.unlink()
                    removed += 1
            print(f"Removed {removed} unreferenced files older than 24 hours.")
        else:
            user = db.scalar(
                select(User).where(
                    User.email == (args.email or settings.admin_email).lower()
                )
            )
            if not user:
                raise SystemExit("User not found")
            password = getpass.getpass("New password (12+ characters): ")
            if len(password) < 12:
                raise SystemExit("Password must contain at least 12 characters")
            if password != getpass.getpass("Confirm password: "):
                raise SystemExit("Passwords do not match")
            user.password_hash = PasswordHasher().hash(password)
            db.execute(delete(Session).where(Session.user_id == user.id))
            print("Password updated and sessions revoked.")


if __name__ == "__main__":
    main()
