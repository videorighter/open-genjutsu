"""Bounded local-only acceptance/load probe. Never submits paid model stages."""

import argparse
import concurrent.futures
import json
import secrets
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
from dotenv import dotenv_values


@contextmanager
def login(base, email, password):
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        response = client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        response.raise_for_status()
        client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
        yield client


def graph(asset):
    def node(id, kind, x):
        return {
            "id": id,
            "type": "studio",
            "position": {"x": x, "y": 0},
            "data": {
                "kind": kind,
                "label": id,
                "provider": "local",
                "model": "ffmpeg" if kind == "output" else "media-input",
                "prompt": "",
                "temperature": 0.7,
                "seed": "42",
                "resolution": "720p",
                **({"assetId": asset} if kind == "video" else {}),
            },
        }

    return {
        "version": 1,
        "title": "Local acceptance probe",
        "nodes": [node("video", "video", 0), node("output", "output", 300)],
        "edges": [
            {"id": "e", "source": "video", "target": "output", "type": "smoothstep"}
        ],
    }


def checked(response):
    response.raise_for_status()
    return response.json()


def run_probe(base, credentials, users=3, jobs_per_user=2):
    if not 1 <= users <= 5 or not 1 <= jobs_per_user <= 2:
        raise ValueError("Probe is bounded to 1–5 users and 1–2 jobs per user")
    with tempfile.TemporaryDirectory(prefix="genjutsu-probe-") as temporary:
        source = Path(temporary) / "source.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=128x128:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(source),
            ],
            check=True,
        )
        password = secrets.token_urlsafe(24)
        accounts = [f"probe-{uuid.uuid4()}@tests.invalid" for _ in range(users)]
        with login(
            base,
            credentials["GENJUTSU_ADMIN_EMAIL"],
            credentials["GENJUTSU_ADMIN_PASSWORD"],
        ) as admin:
            for email in accounts:
                checked(
                    admin.post(
                        "/api/admin/users", json={"email": email, "password": password}
                    )
                )

        def user_probe(email):
            started = time.monotonic()
            with login(base, email, password) as client:
                with source.open("rb") as media:
                    asset = checked(
                        client.post(
                            "/api/assets",
                            files={"file": ("source.mp4", media, "video/mp4")},
                        )
                    )["id"]
                workflow = checked(
                    client.post(
                        "/api/workflows", json={"revision": 0, "graph": graph(asset)}
                    )
                )
                preflight = checked(
                    client.post(f"/api/workflows/{workflow['id']}/validate")
                )
                assert preflight["paid_steps"] == 0 and not preflight["errors"], (
                    "Only validated unpaid local workflows may run"
                )
                pending = []
                for _ in range(jobs_per_user):
                    body = {
                        "revision": workflow["revision"],
                        "request_key": str(uuid.uuid4()),
                    }
                    path = f"/api/workflows/{workflow['id']}/jobs"
                    job = checked(client.post(path, json=body))
                    assert checked(client.post(path, json=body))["id"] == job["id"], (
                        "Duplicate request created a second job"
                    )
                    pending.append(job["id"])
                for id in pending:
                    deadline = time.monotonic() + 120
                    while True:
                        job = checked(client.get(f"/api/jobs/{id}"))
                        if job["status"] == "SUCCEEDED":
                            break
                        assert job["status"] in {"QUEUED", "RUNNING"}, (
                            f"Unexpected job status: {job['status']}"
                        )
                        if time.monotonic() > deadline:
                            raise TimeoutError("Local generation exceeded 120 seconds")
                        time.sleep(0.25)
                    output = next(
                        step for step in job["steps"] if step["node_id"] == "output"
                    )["output"]["asset_id"]
                    response = client.get(f"/api/assets/{output}/content")
                    response.raise_for_status()
                    target = Path(temporary) / f"{id}.mp4"
                    target.write_bytes(response.content)
                    streams = json.loads(
                        subprocess.check_output(
                            [
                                "ffprobe",
                                "-v",
                                "error",
                                "-show_streams",
                                "-of",
                                "json",
                                str(target),
                            ]
                        )
                    )["streams"]
                    assert {stream["codec_type"] for stream in streams} >= {
                        "video",
                        "audio",
                    }, "Result lost video or audio"
                assert len(checked(client.get("/api/jobs"))) == jobs_per_user
                return time.monotonic() - started

        with concurrent.futures.ThreadPoolExecutor(max_workers=users) as pool:
            durations = sorted(pool.map(user_probe, accounts))
        return {
            "users": users,
            "jobs_per_user": jobs_per_user,
            "completed_jobs": users * jobs_per_user,
            "duplicate_requests_reused": users * jobs_per_user,
            "audio_verified_outputs": users * jobs_per_user,
            "paid_calls": 0,
            "user_batch_p95_seconds": round(
                durations[(len(durations) * 95 + 99) // 100 - 1], 3
            ),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--users", type=int, default=3)
    parser.add_argument("--jobs-per-user", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_probe(
        args.url, dotenv_values(args.env_file), args.users, args.jobs_per_user
    )
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
