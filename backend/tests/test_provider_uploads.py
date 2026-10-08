import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from genjutsu import provider_media, providers
from genjutsu.db import Asset, User
from genjutsu.media import asset_path
from genjutsu.schemas import Graph
from genjutsu.validation import validate_execution


def media(settings, id, mime, data=b"owned-file-bytes"):
    file = asset_path(settings, id)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)
    return SimpleNamespace(id=id, size=len(data), mime=mime)


@pytest.mark.asyncio
async def test_fal_upload_streams_without_forwarding_key_and_deduplicates(settings):
    asset = media(settings, "owned-video", "video/mp4")
    calls = []

    async def handle(request):
        calls.append(request)
        if request.method == "POST":
            assert request.headers["Authorization"] == "Key fake-test-key"
            assert json.loads(request.content) == {
                "file_name": "owned-video.mp4",
                "content_type": "video/mp4",
            }
            assert (
                json.loads(request.headers["X-Fal-Object-Lifecycle-Preference"])[
                    "expiration_duration_seconds"
                ]
                == 10800
            )
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://storage.googleapis.com/bucket/file",
                    "file_url": "https://v3.fal.media/owned.mp4",
                },
            )
        assert "Authorization" not in request.headers
        assert await request.aread() == b"owned-file-bytes"
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        urls = await provider_media.upload_inputs(
            client, [asset, asset], "fal", "fake-test-key", settings
        )
    assert urls == {asset.id: "https://v3.fal.media/owned.mp4"}
    assert [r.method for r in calls] == ["POST", "PUT"]


@pytest.mark.asyncio
async def test_replicate_uses_official_multipart_content_field(settings):
    asset = media(settings, "owned-image", "image/png")

    async def handle(request):
        assert str(request.url) == "https://api.replicate.com/v1/files"
        assert request.headers["Authorization"] == "Bearer fake-test-key"
        content = await request.aread()
        assert b'name="content"; filename="owned-image.png"' in content
        assert b"owned-file-bytes" in content
        return httpx.Response(
            200, json={"urls": {"get": "https://api.replicate.com/v1/files/test-file"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await provider_media.upload_inputs(
            client, [asset], "replicate", "fake-test-key", settings
        ) == {asset.id: "https://api.replicate.com/v1/files/test-file"}


@pytest.mark.asyncio
async def test_upload_response_cannot_target_private_address(settings, monkeypatch):
    settings.testing = False
    asset = media(settings, "owned-video", "video/mp4")
    calls = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [
            (
                2,
                1,
                6,
                "",
                ("127.0.0.1" if host == "storage.googleapis.com" else "8.8.8.8", 443),
            )
        ],
    )

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "upload_url": "https://storage.googleapis.com/file",
                "file_url": "https://v3.fal.media/file",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(provider_media.MediaUploadFailed):
            await provider_media.upload_inputs(
                client, [asset], "fal", "fake-test-key", settings
            )
    assert len(calls) == 1 and calls[0].method == "POST"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", ["initiate", "put"])
async def test_failed_upload_never_submits_generation(settings, monkeypatch, fail_at):
    settings.media_delivery = "upload"
    asset = media(settings, "owned-video", "video/mp4")
    calls = []
    original = httpx.AsyncClient

    def handle(request):
        calls.append(request)
        if request.method == "PUT":
            return httpx.Response(503)
        return httpx.Response(
            503 if fail_at == "initiate" else 200,
            json={
                "upload_url": "https://storage.googleapis.com/file",
                "file_url": "https://v3.fal.media/file",
            },
        )

    monkeypatch.setattr(providers, "credential", lambda *args: "fake-test-key")
    monkeypatch.setattr(providers, "inputs_for", lambda *args: ([], [asset], []))
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(providers.UploadRejected):
        await providers.submit_provider(
            None,
            SimpleNamespace(user_id="test"),
            {"data": {"kind": "motion", "provider": "fal", "model": providers.KLING}},
            settings,
        )
    assert all(request.url.host != "queue.fal.run" for request in calls)


@pytest.mark.asyncio
async def test_vace_uses_uploaded_urls_for_masks_and_reference_list(
    settings, monkeypatch
):
    settings.media_delivery = "upload"
    image = media(settings, "owned-image", "image/png")
    video = media(settings, "owned-video", "video/mp4")
    original = httpx.AsyncClient
    payloads = []

    def handle(request):
        if request.url.host == "rest.fal.ai":
            filename = json.loads(request.content)["file_name"]
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://storage.googleapis.com/" + filename,
                    "file_url": "https://v3.fal.media/" + filename,
                },
            )
        if request.method == "PUT":
            return httpx.Response(200)
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"request_id": "request-1"})

    monkeypatch.setattr(providers, "credential", lambda *args: "fake-test-key")
    monkeypatch.setattr(providers, "inputs_for", lambda *args: ([image], [video], []))
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    await providers.submit_provider(
        None,
        SimpleNamespace(user_id="test"),
        {
            "data": {
                "kind": "motion",
                "provider": "fal",
                "model": providers.VACE,
                "prompt": "Follow the motion",
                "providerInput": {"task": "inpainting", "mask_image_url": "$image"},
            }
        },
        settings,
    )
    assert len(payloads) == 1
    assert payloads[0]["ref_image_urls"] == ["https://v3.fal.media/owned-image.png"]
    assert payloads[0]["mask_image_url"] == "https://v3.fal.media/owned-image.png"
    assert payloads[0]["video_url"] == "https://v3.fal.media/owned-video.mp4"


@pytest.mark.parametrize("delivery", ["signed", "upload"])
def test_local_preflight_requires_https_only_for_signed_delivery(
    client, app, settings, image, delivery
):
    settings.media_delivery = delivery
    reference = client.post(
        "/api/assets", files={"file": ("ref.png", image, "image/png")}
    ).json()["id"]
    client.put("/api/credentials/fal", json={"key": "fake-test-key"})
    with app.state.database.session.begin() as db:
        user = db.scalar(select(User))
        video = Asset(
            user_id=user.id,
            filename="video.mp4",
            mime="video/mp4",
            size=10,
            checksum="a" * 64,
            metadata_json={"duration": 3},
        )
        db.add(video)
        db.flush()
        from conftest import graph

        g = graph(video.id)
        motion = json.loads(json.dumps(g["nodes"][1]))
        motion["id"] = "motion"
        motion["data"].update(kind="motion", provider="fal", model=providers.KLING)
        ref = json.loads(json.dumps(g["nodes"][0]))
        ref["id"] = "reference"
        ref["data"].update(kind="reference", assetId=reference)
        g["nodes"].extend([ref, motion])
        g["edges"] = [
            {"id": "a", "source": "video", "target": "motion"},
            {"id": "b", "source": "reference", "target": "motion"},
            {"id": "c", "source": "motion", "target": "output"},
        ]
        settings.testing = False
        result = validate_execution(Graph.model_validate(g), db, user.id, settings)
        assert any("HTTPS" in error for error in result["errors"]) == (
            delivery == "signed"
        )
        if delivery == "upload":
            assert not result["errors"]
            assert any("저장소" in warning for warning in result["warnings"])
