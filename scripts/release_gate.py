"""Fail closed if the repository's human release approval policy is absent."""

import argparse
import json
from pathlib import Path


def validate_gate(environment, branches):
    if environment.get("name") != "release":
        raise ValueError("Configure the GitHub Environment named release")
    reviewers = [
        rule
        for rule in environment.get("protection_rules", [])
        if rule.get("type") == "required_reviewers" and rule.get("reviewers")
    ]
    if not reviewers:
        raise ValueError("release Environment must have at least one required reviewer")
    policy = environment.get("deployment_branch_policy") or {}
    if not policy.get("custom_branch_policies") or policy.get("protected_branches"):
        raise ValueError("release Environment must use selected deployment branches")
    rules = branches.get("branch_policies", [])
    if not rules or any(
        rule.get("name") != "main" or rule.get("type", "branch") != "branch"
        for rule in rules
    ):
        raise ValueError("release Environment must allow only the main branch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", type=Path)
    parser.add_argument("branches", type=Path)
    args = parser.parse_args()
    validate_gate(
        json.loads(args.environment.read_text()), json.loads(args.branches.read_text())
    )
    print("Required release reviewer and main-only deployment policy verified.")


if __name__ == "__main__":
    main()
