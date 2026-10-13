"""OpenRouter /videos adapter: request mapping (unit) and durable execution (real Temporal)."""

import base64
import json
import os
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from temporalio.worker import Replayer
from test_openrouter_catalog import GROK, LING, LIVE, QWEN_IMAGE
from test_temporal import fixture_media, infrastructure, start, wait_until, worker_for

from genjutsu import model_catalog, providers
from genjutsu.api import create_app
from genjutsu.db import Job, now
from genjutsu.workflows import GenerationWorkflow

KEY = "fake-openrouter-key-123"


def node(mode, **options):
    return {
        "model": GROK,
        "seed": "7",
        "providerInput": {"image_mode": mode, "duration": 1, **options},
    }


def test_request_maps_image_modes_and_video_references():
    images = ["data:image/png;base64,AAA", "data:image/png;base64,BBB"]
    video = SimpleNamespace(id="v")
    first = providers.openrouter_video_request(
        node("first_frame"), "go", images, [], {}
    )
    assert first["frame_images"] == [
        {
            "type": "image_url",
            "image_url": {"url": images[0]},
            "frame_type": "first_frame",
        }
    ]
    assert first["seed"] == 7 and first["duration"] == 1 and first["prompt"] == "go"
    both = providers.openrouter_video_request(node("first_last"), "", images, [], {})
    assert [f["frame_type"] for f in both["frame_images"]] == [
        "first_frame",
        "last_frame",
    ]
    assert "prompt" not in both
    ref = providers.openrouter_video_request(
        node("reference"), "x", images[:1], [video], {"v": "https://s/v.mp4"}
    )
    assert "frame_images" not in ref
    assert ref["input_references"] == [
        {"type": "video_url", "video_url": {"url": "https://s/v.mp4"}},
        {"type": "image_url", "image_url": {"url": images[0]}},
    ]


@pytest.mark.parametrize(
    "status, message",
    [(402, "잔액"), (429, "한도"), (400, "거절")],
)
def test_rejections_are_explicit_and_never_ambiguous(status, message):
    with pytest.raises(providers.Rejected, match=message):
        providers.check_submission(httpx.Response(status))


def test_pinned_defaults_match_the_validated_estimate():
    graph = {
        "nodes": [
            {"data": {"provider": "openrouter", "model": GROK, "seed": "42",
                      "providerInput": {"duration": 1}}},
            {"data": {"provider": "fal", "model": GROK, "providerInput": {}}},
        ]
    }  # fmt: skip
    pinned = model_catalog.pin_defaults(graph, LIVE)
    assert pinned["nodes"][0]["data"]["providerInput"] == {
        "resolution": "720p",
        "duration": 1,
        "aspect_ratio": "16:9",
        "image_mode": "first_frame",
    }
    assert pinned["nodes"][0]["data"]["seed"] == ""
    assert pinned["nodes"][1]["data"]["providerInput"] == {}
    assert graph["nodes"][0]["data"]["providerInput"] == {"duration": 1}


class FakeOpenRouter:
    def __init__(self, video, image=b""):
        self.video, self.image = video, image
        self.posts, self.polls, self.cancels = [], 0, 0
        self.chats, self.images = [], []
        self.state, self.drop, self.redirect = "in_progress", False, False
        self.cdn_auth = "unset"
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
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path == "/api/v1/chat/completions":
                    parent.chats.append(json.loads(body))
                    return self.send(
                        {"choices": [{"message": {"content": "a dancer"}}],
                         "usage": {"cost": 0.0001}}
                    )  # fmt: skip
                if self.path == "/api/v1/images":
                    parent.images.append(json.loads(body))
                    return self.send(
                        {"data": [{"b64_json": base64.b64encode(parent.image).decode(),
                                   "media_type": "image/png"}],
                         "usage": {"cost": 0.03}}
                    )  # fmt: skip
                if self.path != "/api/v1/videos":
                    parent.cancels += 1
                    return self.send({"error": "not found"}, 404)
                parent.posts.append(json.loads(body))
                refs = parent.posts[-1].get("input_references", [])
                if "seed" in parent.posts[-1] or any(
                    r.get("video_url", {}).get("url", "").startswith("data:")
                    for r in refs
                ):
                    # Real /videos: unsupported seed or data-URL video reference → 400.
                    return self.send({"error": {"message": "invalid"}}, 400)
                if parent.drop:
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                return self.send(
                    {
                        "id": "gen-vid-1-abc",
                        "polling_url": "ignored",
                        "status": "pending",
                    },
                    202,
                )

            def video_bytes(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(parent.video)))
                self.end_headers()
                self.wfile.write(parent.video)

            def do_GET(self):
                if self.path == "/cdn/video.mp4":
                    parent.cdn_auth = self.headers.get("Authorization")
                    return self.video_bytes()
                if self.path.endswith("/content?index=0"):
                    if self.headers.get("Authorization") != "Bearer " + KEY:
                        return self.send({"error": "unauthorized"}, 401)
                    if parent.redirect:
                        self.send_response(302)
                        self.send_header("Location", "/cdn/video.mp4")
                        self.end_headers()
                        return
                    return self.video_bytes()
                parent.polls += 1
                done = parent.state == "completed"
                return self.send(
                    {"id": "gen-vid-1-abc", "status": parent.state,
                     **({"usage": {"cost": 0.02, "is_byok": False}} if done else {})}
                )  # fmt: skip

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def integration(test):
    return pytest.mark.integration(
        pytest.mark.skipif(
            not os.environ.get("GENJUTSU_TEST_TEMPORAL_ADDRESS"),
            reason="Set GENJUTSU_TEST_TEMPORAL_ADDRESS to run real Temporal tests",
        )(test)
    )


@pytest.fixture
async def stack(settings, tmp_path, image, monkeypatch):
    fake = FakeOpenRouter(fixture_media(tmp_path), image)
    settings.provider_base_urls["openrouter"] = (
        f"http://127.0.0.1:{fake.server.server_port}/api/v1"
    )
    monkeypatch.setitem(model_catalog._live, "models", LIVE)
    temporal = await infrastructure(settings, tmp_path)
    app = create_app(settings, dispatch=False)
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"email": settings.admin_email, "password": settings.admin_password},
        )
        client.headers["X-CSRF-Token"] = client.cookies["genjutsu_csrf"]
        assert client.put("/api/credentials/openrouter", json={"key": KEY}).is_success
        yield SimpleNamespace(
            fake=fake, temporal=temporal, app=app, client=client,
            settings=settings, job=lambda: submit(client, fixture_media(tmp_path), image),
            upload=lambda name, data, mime: client.post(
                "/api/assets", files={"file": (name, data, mime)}
            ).json()["id"],
            video=fixture_media(tmp_path), image=image,
        )  # fmt: skip
    fake.close()


def submit(client, video, image):
    def upload(name, data, mime):
        return client.post("/api/assets", files={"file": (name, data, mime)}).json()[
            "id"
        ]

    def node(id, kind, provider, model, **data):
        return {"id": id, "position": {"x": 0, "y": 0},
                "data": {"kind": kind, "label": id, "provider": provider,
                         "model": model, "prompt": "", **data}}  # fmt: skip

    graph = {
        "version": 1,
        "title": "OpenRouter video",
        "nodes": [
            node(
                "source",
                "video",
                "local",
                "media-input",
                assetId=upload("s.mp4", video, "video/mp4"),
            ),
            node(
                "reference",
                "reference",
                "local",
                "media-input",
                assetId=upload("r.png", image, "image/png"),
            ),
            node(
                "motion",
                "motion",
                "openrouter",
                GROK,
                prompt="drift",
                seed="42",  # Studio default; Grok has no seed support.
                providerInput={"resolution": "480p", "duration": 1},
            ),
            node("output", "output", "local", "ffmpeg"),
        ],  # fmt: skip
        "edges": [
            {"id": "a", "source": "reference", "target": "motion"},
            {"id": "b", "source": "motion", "target": "output"},
        ],
    }
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph}).json()
    plan = client.post(f"/api/workflows/{w['id']}/validate").json()
    assert not plan["errors"] and plan["estimated_cost_usd"] == 0.03, plan
    r = client.post(
        f"/api/workflows/{w['id']}/jobs",
        json={"revision": 1, "request_key": os.urandom(8).hex(), "confirm_paid": True},
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


def motion(client, id):
    return next(
        s
        for s in client.get("/api/jobs/" + id).json()["steps"]
        if s["node_id"] == "motion"
    )


@integration
async def test_video_runs_once_survives_worker_restart_and_records_cost(stack):
    s = stack
    id = s.job()
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, id, s.settings)
        await wait_until(lambda: len(s.fake.posts) == 1 and s.fake.polls >= 1)
    s.fake.state = "completed"
    async with worker_for(s.temporal, s.app, s.settings):
        assert await handle.result() == "SUCCEEDED"
        await Replayer(
            workflows=[GenerationWorkflow], data_converter=s.temporal.data_converter
        ).replay_workflow(await handle.fetch_history())
    sent = s.fake.posts[0]
    assert len(s.fake.posts) == 1
    assert sent["aspect_ratio"] == "16:9"  # Pinned default, not left to the vendor.
    assert sent["frame_images"][0]["image_url"]["url"].startswith("data:image/png")
    assert motion(s.client, id)["output"]["cost_usd"] == 0.02


@integration
async def test_lost_submit_needs_review_and_reconcile_never_reposts(stack):
    s = stack
    s.fake.drop = True
    id = s.job()
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, id, s.settings)
        await handle.result()
    assert s.client.get("/api/jobs/" + id).json()["status"] == "NEEDS_REVIEW"
    s.fake.drop, s.fake.state = False, "completed"
    with s.app.state.database.session.begin() as db:
        db.get(Job, id).updated = now() - timedelta(minutes=10)
    restored = s.client.post(
        f"/api/admin/jobs/{id}/reconcile",
        json={"node_id": "motion", "provider_id": "gen-vid-1-abc"},
    )
    assert restored.status_code == 200, restored.text
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, id, s.settings)
        assert await handle.result() == "SUCCEEDED"
    assert len(s.fake.posts) == 1


@integration
async def test_cancel_sends_no_remote_cancel_and_skips_output(stack):
    s = stack
    id = s.job()
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, id, s.settings)
        await wait_until(lambda: s.fake.polls >= 1)
        assert s.client.post(f"/api/jobs/{id}/cancel").status_code == 200
        polled = s.fake.polls
        # One more poll proves the workflow already passed its cancel_step.
        await wait_until(lambda: s.fake.polls > polled, timeout=30)
        s.fake.state = "completed"
        assert await handle.result() == "CANCELLED"
    steps = {x["node_id"]: x for x in s.client.get("/api/jobs/" + id).json()["steps"]}
    assert s.fake.cancels == 0
    assert steps["motion"]["status"] == "COMPLETE"
    assert steps["output"]["status"] != "COMPLETE"


@integration
async def test_redirected_content_never_receives_the_key(stack):
    s = stack
    s.fake.redirect, s.fake.state = True, "completed"
    id = s.job()
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, id, s.settings)
        assert await handle.result() == "SUCCEEDED"
    assert s.fake.cdn_auth is None


@integration
async def test_expired_result_fails_the_job(stack):
    s = stack
    s.fake.state = "expired"
    id = s.job()
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, id, s.settings)
        assert await handle.result() == "FAILED"
    assert motion(s.client, id)["status"] == "FAILED"


@integration
async def test_analysis_image_and_video_chain_uses_generated_reference(stack):
    s = stack

    def node(id, kind, model, **data):
        provider = "local" if kind in {"video", "output"} else "openrouter"
        return {"id": id, "position": {"x": 0, "y": 0},
                "data": {"kind": kind, "label": id, "provider": provider,
                         "model": model, "prompt": "", **data}}  # fmt: skip

    graph = {
        "version": 1,
        "title": "OpenRouter chain",
        "nodes": [
            node(
                "source",
                "video",
                "media-input",
                assetId=s.upload("s.mp4", s.video, "video/mp4"),
            ),
            node(
                "analysis",
                "analysis",
                LING,
                prompt="describe",
                providerInput={"analysis_input": "video"},
            ),
            node(
                "hero",
                "image",
                QWEN_IMAGE,
                prompt="hero",
                providerInput={"aspect_ratio": "16:9"},
            ),
            node(
                "motion",
                "motion",
                GROK,
                prompt="drift",
                providerInput={"resolution": "480p", "duration": 1},
            ),
            node("output", "output", "ffmpeg"),
        ],  # fmt: skip
        "edges": [
            {"id": "a", "source": "source", "target": "analysis"},
            {"id": "b", "source": "analysis", "target": "hero"},
            {"id": "c", "source": "hero", "target": "motion"},
            {"id": "d", "source": "motion", "target": "output"},
        ],
    }
    w = s.client.post("/api/workflows", json={"revision": 0, "graph": graph}).json()
    plan = s.client.post(f"/api/workflows/{w['id']}/validate").json()
    assert not plan["errors"], plan
    r = s.client.post(
        f"/api/workflows/{w['id']}/jobs",
        json={"revision": 1, "request_key": os.urandom(8).hex(), "confirm_paid": True},
    )
    assert r.status_code == 202, r.text
    s.fake.state = "completed"
    async with worker_for(s.temporal, s.app, s.settings):
        handle = await start(s.temporal, s.app, r.json()["id"], s.settings)
        assert await handle.result() == "SUCCEEDED"
    video_part = s.fake.chats[0]["messages"][0]["content"][1]
    assert video_part["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert s.fake.images[0]["prompt"].endswith("a dancer")  # Analysis text flows in.
    assert s.fake.images[0]["aspect_ratio"] == "16:9"
    frame = s.fake.posts[0]["frame_images"][0]["image_url"]["url"]
    assert frame == "data:image/png;base64," + base64.b64encode(s.image).decode()
    steps = {
        x["node_id"]: x
        for x in s.client.get("/api/jobs/" + r.json()["id"]).json()["steps"]
    }
    assert steps["hero"]["output"]["cost_usd"] == 0.03
    assert len(s.fake.chats) == len(s.fake.images) == len(s.fake.posts) == 1


def test_inline_media_is_bounded_before_any_paid_request(settings):
    big = SimpleNamespace(id="x", mime="video/mp4", size=21 * 1024 * 1024)
    with pytest.raises(providers.Rejected, match="20MB"):
        providers.data_url(settings, big)
