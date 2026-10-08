"""Prepare release artifacts without creating branches, tags or external releases."""

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION_RE = re.compile(rf"{NUMBER}\.{NUMBER}\.{NUMBER}(?:-rc\.[1-9][0-9]*)?")
IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}")
PLATFORM_KEYS = {"db", "temporal-db", "temporal", "ingress"}


def valid_version(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise ValueError("Use MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-rc.N")
    return value


def valid_image(value):
    if not isinstance(value, str) or not IMAGE_RE.fullmatch(value):
        raise ValueError("Image references must be pinned with @sha256:<64 hex digits>")
    return value


def version(root=ROOT):
    package = json.loads((root / "package.json").read_text())
    lock = json.loads((root / "package-lock.json").read_text())
    current = valid_version(package["version"])
    if lock["version"] != current or lock["packages"][""]["version"] != current:
        raise ValueError("package.json and package-lock.json versions differ")
    return current


def notes(value, root=ROOT):
    changelog = (root / "CHANGELOG.md").read_text()
    match = re.search(
        rf"^## {re.escape(value)}\s*\n(.*?)(?=^## |\Z)", changelog, re.M | re.S
    )
    if not match or not match[1].strip():
        raise ValueError(f"CHANGELOG.md needs release notes under '## {value}'")
    return match[1].strip() + "\n"


def schema(root=ROOT):
    revisions = {}
    for path in (root / "backend/migrations/versions").glob("*.py"):
        assignments = {}
        for item in ast.parse(path.read_text()).body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                    }:
                        assignments[target.id] = ast.literal_eval(item.value)
        id = assignments["revision"]
        if id in revisions:
            raise ValueError("Duplicate migration revision")
        revisions[id] = assignments["down_revision"]
    heads = set(revisions) - {parent for parent in revisions.values() if parent}
    if len(heads) != 1:
        raise ValueError("A release must have exactly one migration head")
    head = heads.pop()
    chain = []
    cursor = head
    while cursor is not None:
        if cursor in chain or cursor not in revisions:
            raise ValueError("Invalid migration chain")
        chain.append(cursor)
        cursor = revisions[cursor]
    if set(chain) != set(revisions):
        raise ValueError("Disconnected migrations")
    return {"head": head, "known_revisions": list(reversed(chain))}


def check(root=ROOT):
    current = version(root)
    notes(current, root)
    schema(root)
    platforms = json.loads((root / "deploy/platform-images.json").read_text())
    if set(platforms) != PLATFORM_KEYS:
        raise ValueError("The platform image lock must contain all four services")
    for ref in platforms.values():
        valid_image(ref)
    return current


def manifest(image, compatible=(), root=ROOT, *, allow_dirty=False):
    current = check(root)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
    )
    if dirty and not allow_dirty:
        raise ValueError(
            "A release requires a clean checkout; use --allow-dirty only for a local preview"
        )
    workflow_source = (root / "backend/genjutsu/workflows.py").read_text()
    workflow = re.search(r'@workflow.defn\(name="([A-Za-z0-9_]+)"\)', workflow_source)
    if not workflow:
        raise ValueError("Workflow contract not found")
    result = {
        "format": 1,
        "development": dirty,
        "version": current,
        "revision": revision,
        "image": valid_image(image),
        "platform": json.loads((root / "deploy/platform-images.json").read_text()),
        "schema": schema(root),
        "workflow": workflow[1],
        "rollback_compatible_versions": [valid_version(v) for v in compatible],
    }
    validate_manifest(result)
    return result


def validate_manifest(data):
    if data.get("format") != 1:
        raise ValueError("Unsupported release manifest format")
    valid_version(data["version"])
    valid_image(data["image"])
    if not re.fullmatch(r"[0-9a-f]{40}", data["revision"]):
        raise ValueError("A release requires a full Git revision")
    if set(data["platform"]) != PLATFORM_KEYS:
        raise ValueError("Missing platform image lock")
    for ref in data["platform"].values():
        valid_image(ref)
    known = data["schema"]["known_revisions"]
    if (
        not known
        or len(known) != len(set(known))
        or known[-1] != data["schema"]["head"]
    ):
        raise ValueError("Invalid schema contract")
    if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_]+", v) for v in known):
        raise ValueError("Invalid migration ID")
    if not re.fullmatch(r"[A-Za-z0-9_]+", data["workflow"]):
        raise ValueError("Invalid workflow contract")
    for value in data["rollback_compatible_versions"]:
        valid_version(value)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    bump = commands.add_parser("set-version")
    bump.add_argument("version", type=valid_version)
    build = commands.add_parser("manifest")
    build.add_argument("--image", required=True, type=valid_image)
    build.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Generate a preview that cannot be deployed",
    )
    build.add_argument(
        "--rollback-compatible", action="append", default=[], type=valid_version
    )
    build.add_argument("--output", type=Path, default=ROOT / ".release/release.json")
    show_notes = commands.add_parser("notes")
    show_notes.add_argument("--version", type=valid_version)
    args = parser.parse_args()
    if args.command == "check":
        print(check())
    elif args.command == "set-version":
        current = version()

        def ordering(value):
            stable, _, rc = value.partition("-rc.")
            return (*map(int, stable.split(".")), int(rc) if rc else float("inf"))

        if ordering(args.version) <= ordering(current):
            raise ValueError(
                "New versions must increase; published versions are not reused"
            )
        for name in ("package.json", "package-lock.json"):
            path = ROOT / name
            value = json.loads(path.read_text())
            value["version"] = args.version
            if name == "package-lock.json":
                value["packages"][""]["version"] = args.version
            path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        print(f"{current} -> {args.version}; add release notes before running check")
    elif args.command == "manifest":
        data = manifest(
            args.image, args.rollback_compatible, allow_dirty=args.allow_dirty
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, indent=2) + "\n")
        print(args.output)
    else:
        print(notes(args.version or version()), end="")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from None
