"""Exercise the actual Compose stack with disposable local-only generation jobs."""

import os
import subprocess
import time
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from test_temporal import fixture_media

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GENJUTSU_TEST_COMPOSE_STACK") != "1",
        reason="Opt in with GENJUTSU_TEST_COMPOSE_STACK=1 for a disposable Compose stack",
    ),
]


def test_queue_and_result_survive_api_and_worker_restart(tmp_path):
    env = dotenv_values(".env")
    base = env["GENJUTSU_PUBLIC_URL"]
    password = "Disposable-test-password-123"
    email = "recovery-" + str(uuid.uuid4()) + "@tests.invalid"
    with httpx.Client(base_url=base, timeout=20, trust_env=False) as admin:
        assert (
            admin.post(
                "/api/auth/login",
                json={
                    "email": env["GENJUTSU_ADMIN_EMAIL"],
                    "password": env["GENJUTSU_ADMIN_PASSWORD"],
                },
            ).status_code
            == 200
        )
        assert (
            admin.post(
                "/api/admin/users",
                json={"email": email, "password": password},
                headers={"X-CSRF-Token": admin.cookies["genjutsu_csrf"]},
            ).status_code
            == 201
        )
    with httpx.Client(base_url=base, timeout=20, trust_env=False) as c:
        c.post("/api/auth/login", json={"email": email, "password": password})
        c.headers["X-CSRF-Token"] = c.cookies["genjutsu_csrf"]
        source = c.post(
            "/api/assets",
            files={"file": ("source.mp4", fixture_media(tmp_path), "video/mp4")},
        ).json()["id"]
        from conftest import graph

        w = c.post(
            "/api/workflows", json={"revision": 0, "graph": graph(source)}
        ).json()
        body = {"revision": 1, "request_key": str(uuid.uuid4())}
        subprocess.run(
            ["docker", "compose", "stop", "worker"], check=True, capture_output=True
        )
        try:
            a = c.post("/api/workflows/" + w["id"] + "/jobs", json=body)
            assert a.status_code == 202, a.text
            id = a.json()["id"]
            assert (
                c.post("/api/workflows/" + w["id"] + "/jobs", json=body).json()["id"]
                == id
            )
            subprocess.run(
                ["docker", "compose", "restart", "api"], check=True, capture_output=True
            )
            for _ in range(120):
                try:
                    if c.get("/api/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            else:
                raise AssertionError("API did not recover")
            assert c.get("/api/jobs/" + id).json()["status"] in {"QUEUED", "RUNNING"}
        finally:
            subprocess.run(
                ["docker", "compose", "start", "worker"],
                check=True,
                capture_output=True,
            )
        for _ in range(120):
            job = c.get("/api/jobs/" + id).json()
            if job["status"] == "SUCCEEDED":
                break
            assert job["status"] not in {"FAILED", "NEEDS_REVIEW"}, job
            time.sleep(0.25)
        else:
            raise AssertionError("Queued generation did not resume")
        asset = next(s for s in job["steps"] if s["node_id"] == "output")["output"][
            "asset_id"
        ]
        assert c.get("/api/assets/" + asset + "/content").status_code == 200
        subprocess.run(
            ["docker", "compose", "restart", "api", "worker"],
            check=True,
            capture_output=True,
        )
        for _ in range(120):
            try:
                if c.get("/api/readyz").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        assert c.get("/api/jobs/" + id).json()["status"] == "SUCCEEDED"
        assert c.get("/api/assets/" + asset + "/content").status_code == 200
