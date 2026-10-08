import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from release_gate import validate_gate


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "name": "release",
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "reviewers": [{"type": "User", "reviewer": {"id": 123}}],
                }
            ],
            "deployment_branch_policy": {
                "custom_branch_policies": True,
                "protected_branches": False,
            },
        }
        self.branches = {"branch_policies": [{"name": "main", "type": "branch"}]}

    def test_required_reviewer_and_main_allowed(self):
        validate_gate(self.environment, self.branches)

    def test_unprotected_environment_rejected(self):
        for rules in ([], [{"type": "required_reviewers", "reviewers": []}]):
            env = copy.deepcopy(self.environment)
            env["protection_rules"] = rules
            with self.assertRaises(ValueError):
                validate_gate(env, self.branches)

    def test_wildcard_and_tag_deployments_rejected(self):
        for name, kind in (("*", "branch"), ("main", "tag"), ("feat/*", "branch")):
            with self.assertRaises(ValueError):
                validate_gate(
                    self.environment,
                    {"branch_policies": [{"name": name, "type": kind}]},
                )

    def test_missing_branch_policy_rejected(self):
        with self.assertRaises(ValueError):
            validate_gate(self.environment, {"branch_policies": []})

    def test_tunnel_deploy_uses_pinned_compose_without_tls(self):
        import deploy
        from test_release import fixture

        env = deploy.environment(fixture(), tunnel=True)
        self.assertEqual(Path(env["COMPOSE_FILE"].split(":")[-1]).name, "compose.tunnel.yaml")
        self.assertEqual(env["COMPOSE_PROFILES"], "tunnel")
