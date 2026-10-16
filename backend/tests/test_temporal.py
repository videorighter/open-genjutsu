"""Real Temporal integration. Point GENJUTSU_TEST_TEMPORAL_ADDRESS at a test namespace/server."""

import asyncio
import os
import subprocess
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from temporalio.worker import Replayer, Worker

from genjutsu.activities import Activities
from genjutsu.api import create_app
from genjutsu.db import Job
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


def fixture_media(tmp_path, seconds=1):
    target = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=green:s=64x64:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
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


def setup_job(client, video, audio=None, image=None, clip=None):
    def upload(name, data, mime):
        return client.post("/api/assets", files={"file": (name, data, mime)}).json()[
            "id"
        ]

    source = upload(
        *(
            ("source.png", image, "image/png")
            if image
            else ("source.mp4", video, "video/mp4")
        )
    )

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
        node(
            "source", "reference" if image else "video", "local", "media-input", source
        ),
        node("output", "output", "local", "ffmpeg"),
    ]
    if audio:
        nodes[1]["data"]["providerInput"] = {"audio": audio}
    if clip:
        nodes[0]["data"]["range"] = clip
    pairs = [("source", "output")]
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
        json={"revision": 1, "request_key": str(uuid.uuid4())},
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
        id = setup_job(client, fixture_media(tmp_path))
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


async def test_output_can_drop_audio_or_pass_an_image_through(
    settings, tmp_path, image
):
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"email": settings.admin_email, "password": settings.admin_password},
        )
        client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
        silent = setup_job(client, fixture_media(tmp_path), audio="none")
        still = setup_job(client, None, image=image)
        async with worker_for(temporal, app, settings):
            for id in [silent, still]:
                assert (
                    await (await start(temporal, app, id, settings)).result()
                    == "SUCCEEDED"
                )

        def result(id):
            steps = client.get("/api/jobs/" + id).json()["steps"]
            return next(s for s in steps if s["node_id"] == "output")["output"][
                "asset_id"
            ]

        from genjutsu.db import Asset

        with app.state.database.session() as db:
            assert db.get(Asset, result(silent)).metadata_json["audio"] is False
            # The image result is the uploaded image itself, not a re-encoded copy.
            assert db.get(Asset, result(still)).filename == "source.png"


async def test_source_range_trims_the_video_and_its_audio(settings, tmp_path):
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"email": settings.admin_email, "password": settings.admin_password},
        )
        client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
        id = setup_job(
            client, fixture_media(tmp_path, 4), clip={"start": 1.0, "end": 3.5}
        )
        async with worker_for(temporal, app, settings):
            assert (
                await (await start(temporal, app, id, settings)).result() == "SUCCEEDED"
            )
        steps = {
            s["node_id"]: s["output"]["asset_id"]
            for s in client.get("/api/jobs/" + id).json()["steps"]
        }

        from genjutsu.db import Asset

        with app.state.database.session() as db:
            clip, result = (
                db.get(Asset, steps["source"]),
                db.get(Asset, steps["output"]),
            )
            assert clip.filename == "source_1.0-3.5s.mp4"
            assert abs(result.metadata_json["duration"] - 2.5) < 0.1
            assert result.metadata_json["audio"] is True


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
        id = setup_job(client, fixture_media(tmp_path))
        async with worker_for(temporal, app, settings):
            handle = await start(temporal, app, id, settings)
            assert await handle.result() == "SUCCEEDED"
        assert len(calls) == 2
