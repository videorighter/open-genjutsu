"""Release safety contracts: immutable inputs, rollback gates and no-op previews."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import deploy
import release


def fixture():
    return {
        "format": 1,
        "version": "0.3.0",
        "revision": "a" * 40,
        "image": "ghcr.io/videorighter/open-genjutsu@sha256:" + "b" * 64,
        "platform": json.loads((ROOT / "deploy/platform-images.json").read_text()),
        "schema": {"head": "0003", "known_revisions": ["0001", "0002", "0003"]},
        "workflow": "GenerationWorkflowV1",
        "rollback_compatible_versions": [],
    }


class ReleaseContracts(unittest.TestCase):
    def test_supported_versions_and_injection_rejection(self):
        for version in ("0.3.0", "1.0.0-rc.1"):
            self.assertEqual(release.valid_version(version), version)
        for version in ("01.2.0", "v0.3.0", "0.3.0-rc.0", "0.3.0\nFAKE=1", "$(whoami)"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.valid_version(version)

    def test_mutable_images_are_rejected(self):
        for ref in (
            "open-genjutsu:local",
            "ghcr.io/repo:latest",
            "ghcr.io/repo:v0.3.0",
            "repo@sha256:abc",
        ):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                release.valid_image(ref)

    def test_manifest_requires_all_platform_images(self):
        data = fixture()
        del data["platform"]["temporal-db"]
        with self.assertRaises(ValueError):
            release.validate_manifest(data)

    def test_version_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"version":"0.3.0"}')
            (root / "package-lock.json").write_text(
                '{"version":"0.2.0","packages":{"":{"version":"0.3.0"}}}'
            )
            with self.assertRaises(ValueError):
                release.version(root)

    def test_missing_notes_and_branched_schema_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CHANGELOG.md").write_text("## Unreleased\n- Pending\n")
            with self.assertRaises(ValueError):
                release.notes("0.3.0", root)
            path = root / "backend/migrations/versions"
            path.mkdir(parents=True)
            (path / "first.py").write_text('revision="0001"\ndown_revision=None\n')
            (path / "second.py").write_text('revision="0002"\ndown_revision=None\n')
            with self.assertRaises(ValueError):
                release.schema(root)

    def test_dry_run_executes_no_docker_or_git_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(fixture()))
            with (
                patch.object(sys, "argv", ["deploy.py", str(path)]),
                patch.object(deploy, "apply") as apply,
            ):
                deploy.main()
                apply.assert_not_called()

    def test_rollback_requires_explicit_compatible_version(self):
        old = fixture()
        old["version"] = "0.2.0"
        with self.assertRaises(ValueError):
            deploy.rollback_allowed(fixture(), old, "0003")
        current = fixture()
        current["rollback_compatible_versions"] = ["0.2.0"]
        deploy.rollback_allowed(current, old, "0003")

    def test_uncommitted_preview_cannot_deploy(self):
        target = fixture()
        target["development"] = True
        with patch.object(deploy, "compose") as compose, self.assertRaises(ValueError):
            deploy.apply(target)
        compose.assert_not_called()

    def test_schema_and_workflow_changes_block_image_rollback(self):
        current = fixture()
        current["rollback_compatible_versions"] = ["0.2.0"]
        old = fixture()
        old["version"] = "0.2.0"
        for change in ("database", "schema", "workflow", "platform"):
            with self.subTest(change=change):
                target = copy.deepcopy(old)
                head = "0004" if change == "database" else "0003"
                if change == "schema":
                    target["schema"] = {
                        "head": "0002",
                        "known_revisions": ["0001", "0002"],
                    }
                if change == "workflow":
                    target["workflow"] = "GenerationWorkflowV2"
                if change == "platform":
                    target["platform"]["db"] = "postgres@sha256:" + "c" * 64
                with self.assertRaises(ValueError):
                    deploy.rollback_allowed(current, target, head)

    def test_backend_and_release_tool_use_same_version(self):
        spec = importlib.util.spec_from_file_location(
            "app_version", ROOT / "backend/genjutsu/version.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.VERSION, release.check())

    def test_check_and_manifest_cli_do_not_change_git_state(self):
        before = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release.json"
            subprocess.run(
                [sys.executable, "scripts/release.py", "check"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    "scripts/release.py",
                    "manifest",
                    "--image",
                    fixture()["image"],
                    "--allow-dirty",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            data = release.validate_manifest(json.loads(output.read_text()))
            self.assertEqual(data["version"], release.version())
        self.assertEqual(
            before, subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        )


if __name__ == "__main__":
    unittest.main()
