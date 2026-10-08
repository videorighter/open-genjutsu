"""Backup success and race failure behavior with a disposable fake Docker command."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BackupContracts(unittest.TestCase):
    def simulate(self, *, leave_stopped=False, race=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copyfile(ROOT / "scripts/backup.sh", root / "scripts/backup.sh")
            (root / ".env").write_text("GENJUTSU_SECRET_KEY=disposable-test-secret\n")
            bin = root / "bin"
            bin.mkdir()
            docker = bin / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                "import json,os,sys\n"
                "with open(os.environ['DOCKER_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                "if os.environ.get('TEST_RACE')=='1' and 'run' in sys.argv and 'check-backup' in sys.argv: sys.exit(17)\n"
                "if 'pg_dump' in sys.argv or 'pg_dumpall' in sys.argv or 'tar' in sys.argv: print('disposable-fixture')\n"
            )
            docker.chmod(0o755)
            log = root / "docker.log"
            env = dict(
                os.environ,
                PATH=str(bin) + os.pathsep + os.environ["PATH"],
                DOCKER_LOG=str(log),
                TEST_RACE="1" if race else "0",
            )
            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts/backup.sh"),
                    *(["--leave-stopped"] if leave_stopped else []),
                    "backups/check",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            if not race:
                for name in (
                    "application.dump",
                    "temporal.sql",
                    "media.tar",
                    "environment.env",
                    "SHA256SUMS",
                ):
                    path = root / "backups/check" / name
                    self.assertTrue(path.is_file())
                    self.assertEqual(path.stat().st_mode & 0o077, 0)
                subprocess.run(
                    ["sha256sum", "-c", "backups/check/SHA256SUMS"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
            else:
                self.assertFalse((root / "backups/check/application.dump").exists())
            return result.returncode, calls

    def test_success_restarts_services_and_preserves_checksums(self):
        status, calls = self.simulate()
        self.assertEqual(status, 0)
        self.assertEqual(calls[-1], ["compose", "start", "temporal", "api", "worker"])

    def test_deployment_backup_keeps_writers_stopped(self):
        status, calls = self.simulate(leave_stopped=True)
        self.assertEqual(status, 0)
        self.assertFalse(any("start" in call for call in calls))
        self.assertIn(["compose", "stop", "api", "worker"], calls)
        self.assertIn(["compose", "stop", "temporal"], calls)

    def test_racing_submission_aborts_backup_and_recovers_services(self):
        status, calls = self.simulate(leave_stopped=True, race=True)
        self.assertEqual(status, 17)
        self.assertEqual(calls[-1], ["compose", "start", "temporal", "api", "worker"])
