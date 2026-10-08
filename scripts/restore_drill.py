"""Restore a coordinated backup into new disposable volumes and verify real generation.

Never changes the source stack or restores over existing volumes. Run on a spare host
for a physical host recovery test; a same-host drill proves backup completeness only.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from dotenv import dotenv_values
from service_probe import run_probe

ROOT = Path(__file__).resolve().parent.parent
FILES = {"application.dump", "temporal.sql", "media.tar", "environment.env"}


def verify_backup(backup):
    seen = set()
    for line in (backup / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split(maxsplit=1)
        name = Path(filename.lstrip("*")).name
        if name not in FILES or name in seen:
            raise ValueError("Backup checksum file has unexpected or duplicate entries")
        with (backup / name).open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != digest:
                raise ValueError(f"Backup checksum mismatch: {name}")
        seen.add(name)
    if seen != FILES:
        raise ValueError("Backup checksum file is incomplete")


VERIFY_RESTORED = """
import asyncio, hashlib, json
from pathlib import Path
from sqlalchemy import select, func
from temporalio.worker import Replayer
from genjutsu.config import get_settings
from genjutsu.db import Database, Asset, Credential, Job
from genjutsu.security import cipher
from genjutsu.temporal_client import connect, workflow_id
from genjutsu.workflows import GenerationWorkflow
settings = get_settings()
database = Database(settings)
with database.session() as db:
    assets = list(db.scalars(select(Asset)))
    for a in assets:
        path = settings.data_dir / "assets" / a.id
        assert path.stat().st_size == a.size, "Restored media size differs"
        with path.open("rb") as file:
            assert hashlib.file_digest(file, "sha256").hexdigest() == a.checksum, "Restored media checksum differs"
    credentials = list(db.scalars(select(Credential)))
    for credential in credentials:
        assert cipher(settings.secret_key).decrypt(credential.encrypted_key.encode())
    job = db.scalar(select(Job).where(Job.status == "SUCCEEDED", Job.dispatched.is_(True)).order_by(Job.created).limit(1))
    report = {"restored_media_verified": len(assets), "restored_keys_decrypted": len(credentials), "restored_jobs": db.scalar(select(func.count(Job.id)))}
    if not job:
        raise RuntimeError("Backup has no completed Temporal workflow to replay")
    id = workflow_id(job)
async def replay():
    client = await connect(settings)
    history = await client.get_workflow_handle(id).fetch_history()
    await Replayer(workflows=[GenerationWorkflow], data_converter=client.data_converter).replay_workflow(history)
asyncio.run(replay())
report["restored_temporal_histories_replayed"] = 1
print(json.dumps(report))
"""


def drill(backup, image, port=18080):
    verify_backup(backup)
    credentials = dotenv_values(backup / "environment.env")
    project = "genjutsu-dr-" + uuid.uuid4().hex[:12]
    env = dict(os.environ)
    # Do not inherit a production release's Compose project or ingress profile.
    for name in ("COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME"):
        env.pop(name, None)
    env["HTTP_PORT"] = str(port)
    env["GENJUTSU_PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    env["GENJUTSU_SECURE_COOKIES"] = "false"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="genjutsu-dr-") as temporary:
        private = Path(temporary) / ".env"
        private.write_bytes((backup / "environment.env").read_bytes())
        private.chmod(0o600)
        override = Path(temporary) / "compose.dr.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        name: {
                            "image": image,
                            "build": None,
                            "env_file": [str(private)],
                            "environment": {
                                "GENJUTSU_PUBLIC_URL": env["GENJUTSU_PUBLIC_URL"],
                                "GENJUTSU_SECURE_COOKIES": "false",
                            },
                        }
                        for name in ("api", "worker")
                    }
                }
            )
        )
        command = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(private),
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(override),
        ]

        def compose(args, input=None, capture=False):
            # Keep dump SQL/credentials out of logs even on restoration failures.
            result = subprocess.run(
                [*command, *args],
                env=env,
                input=None if hasattr(input, "read") else input,
                stdin=input if hasattr(input, "read") else None,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode:
                errors = []
                for line in result.stderr.decode(errors="replace").splitlines():
                    if "ERROR:" in line or "FATAL:" in line:
                        for value in credentials.values():
                            if value and len(value) >= 8:
                                line = line.replace(value, "[redacted]")
                        errors.append(line)
                raise RuntimeError(
                    f"DR Compose operation failed: {args[0]} (exit {result.returncode}); {'; '.join(errors)}"
                )
            return result.stdout

        try:
            compose(["up", "-d", "--no-build", "--wait", "db", "temporal-db"])
            with (backup / "application.dump").open("rb") as dump:
                compose(
                    [
                        "exec",
                        "-T",
                        "db",
                        "pg_restore",
                        "-U",
                        "genjutsu",
                        "-d",
                        "genjutsu",
                        "--no-owner",
                        "--exit-on-error",
                    ],
                    dump,
                )
            # POSTGRES_USER=temporal creates an empty database of the same name.
            # Only this drill's newly created volume is addressed here.
            compose(
                [
                    "exec",
                    "-T",
                    "temporal-db",
                    "dropdb",
                    "-U",
                    "temporal",
                    "--maintenance-db=postgres",
                    "temporal",
                ]
            )
            sql_path = Path(temporary) / "temporal.filtered.sql"
            count = 0
            # Stream large dumps and remove only the exact bootstrap role statement.
            with (
                (backup / "temporal.sql").open("rb") as source,
                sql_path.open("xb") as destination,
            ):
                sql_path.chmod(0o600)
                for line in source:
                    if line.rstrip(b"\r\n") == b"CREATE ROLE temporal;":
                        count += 1
                    else:
                        destination.write(line)
            if count != 1:
                raise ValueError("Expected one bootstrap role in Temporal backup")
            with sql_path.open("rb") as sql:
                compose(
                    [
                        "exec",
                        "-T",
                        "temporal-db",
                        "psql",
                        "-U",
                        "temporal",
                        "-d",
                        "postgres",
                        "-v",
                        "ON_ERROR_STOP=1",
                    ],
                    sql,
                )
            with (backup / "media.tar").open("rb") as media:
                compose(
                    [
                        "run",
                        "--rm",
                        "--no-deps",
                        "-T",
                        "api",
                        "tar",
                        "-C",
                        "/data",
                        "-xf",
                        "-",
                    ],
                    media,
                )
            compose(["up", "-d", "--no-build", "--wait", "--wait-timeout", "180"])
            report = json.loads(
                compose(
                    ["exec", "-T", "api", "python", "-c", VERIFY_RESTORED], capture=True
                )
            )
            report["generation_probe"] = run_probe(
                env["GENJUTSU_PUBLIC_URL"], credentials, users=1, jobs_per_user=1
            )
            report["restore_and_probe_seconds"] = round(time.monotonic() - started, 3)
            report["isolation"] = "new Compose project and empty volumes on this host"
            return report
        finally:
            # The generated project name cannot address the source project's volumes.
            compose(["down", "--volumes", "--remove-orphans"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument(
        "--image",
        required=True,
        help="Application image matching the backup schema/workflow contract",
    )
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = drill(args.backup.resolve(), args.image, args.port)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
