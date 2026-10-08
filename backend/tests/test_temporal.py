"""Real Temporal integration. Point GENJUTSU_TEST_TEMPORAL_ADDRESS at a test namespace/server."""

import asyncio
import json
import os
import subprocess
import threading
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from temporalio.worker import Replayer, Worker

from genjutsu.activities import Activities
from genjutsu.api import create_app
from genjutsu.db import Job, Step, now
from genjutsu.temporal_client import connect, workflow_id
from genjutsu.workflows import GenerationWorkflow

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("GENJUTSU_TEST_TEMPORAL_ADDRESS"),
        reason="Set GENJUTSU_TEST_TEMPORAL_ADDRESS to run real Temporal tests",
    ),
]


class FakeProvider:
    def __init__(self, video):
        self.video = video
        self.posts = 0
        self.polls = 0
        self.ready = False
        self.cancelled = False
        self.drop = False
        self.inputs = []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, body, status=200):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path.endswith("/cancel"):
                    parent.cancelled = True
                    return self.send({})
                parent.posts += 1
                parent.inputs.append(data)
                if parent.drop:
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                base = f"http://127.0.0.1:{parent.server.server_port}/fal/fal-ai/wan/requests/request-1"
                return self.send(
                    {
                        "request_id": "request-1",
                        "status_url": base + "/status",
                        "response_url": base,
                        "cancel_url": base + "/cancel",
                    }
                )

            def do_GET(self):
                if self.path == "/video.mp4":
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(parent.video)))
                    self.end_headers()
                    self.wfile.write(parent.video)
                    return
                if self.path.endswith("/status"):
                    parent.polls += 1
                    return self.send(
                        {
                            "status": "CANCELLED"
                            if parent.cancelled
                            else "COMPLETED"
                            if parent.ready
                            else "IN_QUEUE"
                        }
                    )
                return self.send(
                    {
                        "video": {
                            "url": f"http://127.0.0.1:{parent.server.server_port}/video.mp4"
                        }
                    }
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def fixture_media(tmp_path):
    target = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=64x64:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            "-c:a",
            "aac",
            str(target),
        ],
        check=True,
    )
    return target.read_bytes()


def setup_job(client, video, image, remote=True):
    def upload(name, data, mime):
        return client.post("/api/assets", files={"file": (name, data, mime)}).json()[
            "id"
        ]

    source = upload("source.mp4", video, "video/mp4")
    ref = upload("ref.png", image, "image/png")

    def node(id, kind, provider, model, asset=None):
        return {
            "id": id,
            "type": "studio",
            "position": {"x": 0, "y": 0},
            "data": {
                "kind": kind,
                "label": id,
                "provider": provider,
                "model": model,
                "prompt": "",
                "temperature": 0.7,
                "seed": "42",
                "resolution": "720p",
                **({"assetId": asset} if asset else {}),
            },
        }

    nodes = [
        node("source", "video", "local", "media-input", source),
        node("output", "output", "local", "ffmpeg"),
    ]
    pairs = [("source", "output")]
    if remote:
        nodes.insert(1, node("reference", "reference", "local", "media-input", ref))
        nodes.insert(
            2, node("motion", "motion", "fal", "fal-ai/wan/v2.2-14b/animate/move")
        )
        pairs = [("source", "motion"), ("reference", "motion"), ("motion", "output")]
        assert (
            client.put(
                "/api/credentials/fal", json={"key": "fake-test-key-123"}
            ).status_code
            == 200
        )
    graph = {
        "version": 1,
        "title": "Temporal test",
        "nodes": nodes,
        "edges": [
            {"id": str(i), "source": a, "target": b} for i, (a, b) in enumerate(pairs)
        ],
    }
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph}).json()
    r = client.post(
        "/api/workflows/" + w["id"] + "/jobs",
        json={"revision": 1, "request_key": str(uuid.uuid4()), "confirm_paid": remote},
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


async def infrastructure(settings, tmp_path):
    settings.temporal_enabled = True
    settings.temporal_address = os.environ["GENJUTSU_TEST_TEMPORAL_ADDRESS"]
    settings.temporal_task_queue = "test-" + str(uuid.uuid4())
    return await connect(settings)


def worker_for(client, app, settings):
    a = Activities(app.state.database, settings)
    return Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[GenerationWorkflow],
        activities=[
            a.load_job,
            a.cancelled,
            a.execute_step,
            a.poll_step,
            a.cancel_step,
            a.finish_job,
        ],
    )


async def start(client, app, id, settings):
    with app.state.database.session() as db:
        j = db.get(Job, id)
        wid = workflow_id(j)
    return await client.start_workflow(
        "GenerationWorkflowV1",
        id,
        id=wid,
        task_queue=settings.temporal_task_queue,
        execution_timeout=timedelta(seconds=120),
    )


async def wait_until(fn, timeout=15):
    for _ in range(timeout * 10):
        if fn():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("Condition timed out")


async def test_local_pipeline_real_temporal_and_audio(settings, tmp_path, image):
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"email": settings.admin_email, "password": settings.admin_password},
        )
        client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
        id = setup_job(client, fixture_media(tmp_path), image, remote=False)
        async with worker_for(temporal, app, settings):
            handle = await start(temporal, app, id, settings)
            assert await handle.result() == "SUCCEEDED"
            await Replayer(
                workflows=[GenerationWorkflow], data_converter=temporal.data_converter
            ).replay_workflow(await handle.fetch_history())
        result = client.get("/api/jobs/" + id).json()
        assert result["status"] == "SUCCEEDED"
        output = next(s for s in result["steps"] if s["node_id"] == "output")["output"][
            "asset_id"
        ]
        data = client.get(f"/api/assets/{output}/content?download=true")
        assert data.status_code == 200 and len(data.content) > 100
        from genjutsu.db import Asset

        with app.state.database.session() as db:
            assert db.get(Asset, output).metadata_json["audio"] is True


async def test_provider_job_survives_worker_restart_without_resubmission(
    settings, tmp_path, image
):
    video = fixture_media(tmp_path)
    fake = FakeProvider(video)
    settings.provider_base_urls["fal"] = (
        f"http://127.0.0.1:{fake.server.server_port}/fal"
    )
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={
                    "email": settings.admin_email,
                    "password": settings.admin_password,
                },
            )
            client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
            id = setup_job(client, video, image)
            async with worker_for(temporal, app, settings):
                handle = await start(temporal, app, id, settings)
                await wait_until(lambda: fake.posts == 1)
                with app.state.database.session() as db:
                    assert (
                        db.scalar(
                            select(Step).where(
                                Step.job_id == id, Step.node_id == "motion"
                            )
                        ).provider_id
                        == "request-1"
                    )
            fake.ready = True
            async with worker_for(temporal, app, settings):
                assert await handle.result() == "SUCCEEDED"
            assert fake.posts == 1 and fake.polls >= 1
    finally:
        fake.close()


async def test_lost_submit_response_requires_review_and_never_repeats_post(
    settings, tmp_path, image
):
    video = fixture_media(tmp_path)
    fake = FakeProvider(video)
    fake.drop = True
    settings.provider_base_urls["fal"] = (
        f"http://127.0.0.1:{fake.server.server_port}/fal"
    )
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={
                    "email": settings.admin_email,
                    "password": settings.admin_password,
                },
            )
            client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
            id = setup_job(client, video, image)
            async with worker_for(temporal, app, settings):
                handle = await start(temporal, app, id, settings)
                await handle.result()
            j = client.get("/api/jobs/" + id).json()
            assert j["status"] == "NEEDS_REVIEW" and fake.posts == 1
            assert (
                next(s for s in j["steps"] if s["node_id"] == "motion")["status"]
                == "UNKNOWN"
            )
            fake.drop = False
            fake.ready = True
            with app.state.database.session.begin() as db:
                db.get(Job, id).updated = now() - timedelta(minutes=10)
            restored = client.post(
                f"/api/admin/jobs/{id}/reconcile",
                json={"node_id": "motion", "provider_id": "request-1"},
            )
            assert restored.status_code == 200, restored.text
            async with worker_for(temporal, app, settings):
                handle = await start(temporal, app, id, settings)
                assert await handle.result() == "SUCCEEDED"
            assert fake.posts == 1
    finally:
        fake.close()


async def test_cancel_waits_for_provider_and_never_runs_output(
    settings, tmp_path, image
):
    video = fixture_media(tmp_path)
    fake = FakeProvider(video)
    settings.provider_base_urls["fal"] = (
        f"http://127.0.0.1:{fake.server.server_port}/fal"
    )
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={
                    "email": settings.admin_email,
                    "password": settings.admin_password,
                },
            )
            client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
            id = setup_job(client, video, image)
            async with worker_for(temporal, app, settings):
                handle = await start(temporal, app, id, settings)
                await wait_until(lambda: fake.posts == 1)
                assert client.post("/api/jobs/" + id + "/cancel").status_code == 200
                assert await handle.result() == "CANCELLED"
            j = client.get("/api/jobs/" + id).json()
            assert j["status"] == "CANCELLED" and fake.cancelled
            assert (
                next(s for s in j["steps"] if s["node_id"] == "output")["status"]
                == "PENDING"
            )
    finally:
        fake.close()


async def test_local_ffmpeg_failure_is_retried_safely(
    settings, tmp_path, image, monkeypatch
):
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    original = Activities.encode_output
    calls = []

    def temporary_failure(self, *args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Injected local encoding failure")
        return original(self, *args)

    monkeypatch.setattr(Activities, "encode_output", temporary_failure)
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"email": settings.admin_email, "password": settings.admin_password},
        )
        client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
        id = setup_job(client, fixture_media(tmp_path), image, remote=False)
        async with worker_for(temporal, app, settings):
            handle = await start(temporal, app, id, settings)
            assert await handle.result() == "SUCCEEDED"
        assert len(calls) == 2
