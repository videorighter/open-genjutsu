"""Generate local credentials without printing secrets or replacing an existing .env."""

import secrets
from pathlib import Path

path = Path(__file__).resolve().parent.parent / ".env"
if path.exists():
    raise SystemExit(
        ".env already exists; edit it explicitly instead of replacing keys."
    )
text = (path.parent / ".env.example").read_text()
for key in [
    "POSTGRES_PASSWORD",
    "TEMPORAL_POSTGRES_PASSWORD",
    "GENJUTSU_SECRET_KEY",
    "GENJUTSU_ADMIN_PASSWORD",
]:
    text = text.replace(f"{key}=CHANGE_ME", f"{key}={secrets.token_urlsafe(36)}")
fd = path.open("x")
fd.write(text)
fd.close()
path.chmod(0o600)
print(
    "Created .env with random secrets. Set the admin email and inspect the file locally."
)
