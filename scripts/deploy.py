"""Digest-pinned single-host deployments; dry-run unless --apply is explicit."""

import argparse
import fcntl
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from release import ROOT, validate_manifest

STATE = ROOT / ".release"
PLATFORM_ENV = {
    "db": "GENJUTSU_DATABASE_IMAGE",
    "temporal-db": "GENJUTSU_TEMPORAL_DATABASE_IMAGE",
    "temporal": "GENJUTSU_TEMPORAL_IMAGE",
    "ingress": "GENJUTSU_INGRESS_IMAGE",
}


def environment(manifest, image=None):
    env = dict(os.environ)
    env["COMPOSE_FILE"] = (
        str(ROOT / "compose.yaml") + ":" + str(ROOT / "compose.release.yaml")
    )
    env["COMPOSE_PATH_SEPARATOR"] = ":"
    env["GENJUTSU_IMAGE"] = image or manifest["image"]
    for key, value in PLATFORM_ENV.items():
        env[value] = manifest["platform"][key]
    return env


def run(args, env, capture=False):
    return subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def compose(args, env, tls=False, capture=False):
    return run(
        ["docker", "compose", *(["--profile", "tls"] if tls else []), *args],
        env,
        capture,
    )


def write(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def rollback_allowed(current, target, schema_head):
    if not current or target["version"] not in current["rollback_compatible_versions"]:
        raise ValueError(
            "Current release does not explicitly permit this rollback version"
        )
    if current["schema"] != target["schema"] or schema_head != target["schema"]["head"]:
        raise ValueError(
            "Schema differs: restore the coordinated backup instead of image rollback"
        )
    if (
        current["workflow"] != target["workflow"]
        or current["platform"] != target["platform"]
    ):
        raise ValueError(
            "Workflow/platform contract differs: image rollback is blocked"
        )


def inspect(ref, env):
    return json.loads(run(["docker", "image", "inspect", ref], env, True))[0]


def verify_ready(url, target, env, tls):
    # Probe loopback directly; a configured proxy must not intercept local health requests.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with opener.open(url.rstrip("/") + "/api/readyz", timeout=3) as response:
                assert json.load(response)["status"] == "ready"
            with opener.open(url.rstrip("/") + "/api/version", timeout=3) as response:
                metadata = json.load(response)
            if metadata != {
                "version": target["version"],
                "revision": target["revision"],
            }:
                raise ValueError(
                    "Running API version/revision does not match the release"
                )
            compose(
                [
                    "exec",
                    "-T",
                    "worker",
                    "python",
                    "-m",
                    "genjutsu.maintenance",
                    "check-worker",
                ],
                env,
                tls,
            )
            return
        except (OSError, subprocess.CalledProcessError, AssertionError):
            time.sleep(2)
    raise ValueError(
        "Readiness/worker checks failed; no automatic rollback was performed"
    )


def apply(target, *, rollback=False, tls=False, url="http://127.0.0.1:8000"):
    if target.get("development", False):
        raise ValueError(
            "Development previews cannot be deployed; use an official clean-checkout release manifest"
        )
    env = environment(target)
    pending = STATE / "pending.json"
    deployed = STATE / "deployed.json"
    current_path = pending if pending.exists() else deployed
    current = (
        validate_manifest(json.loads(current_path.read_text()))
        if current_path.exists()
        else None
    )
    if pending.exists() and not rollback:
        raise ValueError(
            "An incomplete deployment exists. Resolve it or perform an explicitly compatible rollback"
        )
    compose(["config", "--quiet"], env, tls)
    api_id = compose(["ps", "--all", "--quiet", "api"], env, tls, True).strip()
    previous_image = None
    if api_id:
        container = json.loads(run(["docker", "inspect", api_id], env, True))[0]
        if not container["State"]["Running"]:
            raise ValueError("Existing API is stopped; recover it before deploying")
        previous_image = container["Config"]["Image"]
        schema_head = compose(
            [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "genjutsu",
                "-d",
                "genjutsu",
                "-Atc",
                "SELECT version_num FROM alembic_version",
            ],
            env,
            tls,
            True,
        ).strip()
        if rollback:
            rollback_allowed(current, target, schema_head)
        elif schema_head not in target["schema"]["known_revisions"]:
            raise ValueError(
                "Current database is not an ancestor of the target release"
            )
        # Platform changes need a separate maintenance plan, never an incidental app update.
        for service in ("db", "temporal-db", "temporal", *(["ingress"] if tls else [])):
            id = compose(["ps", "--quiet", service], env, tls, True).strip()
            if not id:
                raise ValueError(f"Existing platform service {service} is not running")
            actual = json.loads(run(["docker", "inspect", id], env, True))[0]["Image"]
            run(["docker", "pull", target["platform"][service]], env)
            if actual != inspect(target["platform"][service], env)["Id"]:
                raise ValueError(
                    f"Platform image changed for {service}; prepare a separate upgrade"
                )
    elif rollback:
        raise ValueError("Rollback requires an existing deployment")
    elif compose(["ps", "--all", "--quiet", "db"], env, tls, True).strip():
        raise ValueError(
            "Database exists without an API; recover the existing stack first"
        )

    compose(["pull", "api", "worker"], env, tls)
    labels = inspect(target["image"], env)["Config"]["Labels"] or {}
    if (
        labels.get("org.opencontainers.image.version") != target["version"]
        or labels.get("org.opencontainers.image.revision") != target["revision"]
    ):
        raise ValueError("Image labels do not match the release manifest")
    if previous_image:
        old_env = environment(target, previous_image)
        backup = (
            ROOT
            / "backups"
            / ("deploy-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        )
        run(["bash", "scripts/backup.sh", "--leave-stopped", str(backup)], old_env)
    write(pending, target)
    print(
        "Applying release. Failures leave pending.json and backups for explicit recovery."
    )
    compose(["up", "-d", "--no-build", "--wait", "--wait-timeout", "180"], env, tls)
    verify_ready(url, target, env, tls)
    if deployed.exists():
        write(STATE / "previous.json", json.loads(deployed.read_text()))
    write(deployed, target)
    # This file contains image references only, never credentials.
    release_env = {
        "GENJUTSU_IMAGE": target["image"],
        **{value: target["platform"][key] for key, value in PLATFORM_ENV.items()},
    }
    (STATE / "images.env").write_text(
        "".join(f"{k}={v}\n" for k, v in release_env.items())
    )
    pending.unlink()
    print(f"Deployed {target['version']} ({target['revision']})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="Local API URL, including a custom HTTP_PORT",
    )
    args = parser.parse_args()
    target = validate_manifest(json.loads(args.manifest.read_text()))
    print(
        f"{'Rollback' if args.rollback else 'Deploy'} {target['version']} at {target['revision']}"
    )
    print(f"Application image: {target['image']}")
    if not args.apply:
        print("Dry-run: no Docker, Git, branch, PR or deployment changes.")
        print(
            "Apply: verify image/platform; require no active jobs; backup and stop writers; start pinned images; verify API and worker."
        )
        return
    STATE.mkdir(exist_ok=True)
    with (STATE / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        apply(target, rollback=args.rollback, tls=args.tls, url=args.url)


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        KeyError,
        BlockingIOError,
        subprocess.CalledProcessError,
    ) as exc:
        raise SystemExit(str(exc)) from None
