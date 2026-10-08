import json
from types import SimpleNamespace

import httpx
import pytest

from genjutsu import providers


@pytest.mark.asyncio
async def test_kling_options_reach_vendor_and_cannot_override_owned_media(
    settings, monkeypatch
):
    payloads = []
    original = httpx.AsyncClient

    def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"request_id": "test-ticket"})

    monkeypatch.setattr(providers, "credential", lambda *args: "fake-test-key")
    monkeypatch.setattr(
        providers,
        "inputs_for",
        lambda *args: (
            [SimpleNamespace(id="owned-image")],
            [SimpleNamespace(id="owned-video")],
            [],
        ),
    )
    monkeypatch.setattr(providers, "allowed_remote", lambda url, *args, **kwargs: url)
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    await providers.submit_provider(
        None,
        SimpleNamespace(user_id="test-user"),
        {
            "data": {
                "kind": "motion",
                "provider": "fal",
                "model": providers.KLING,
                "prompt": "Preserve the character.",
                "seed": "42",
                "providerInput": {
                    "character_orientation": "image",
                    "keep_original_sound": False,
                    "video_url": "https://other.example/video",
                },
            },
        },
        settings,
    )
    assert len(payloads) == 1
    assert payloads[0]["character_orientation"] == "image"
    assert payloads[0]["keep_original_sound"] is False
    assert payloads[0]["prompt"] == "Preserve the character."
    assert "owned-video/content?" in payloads[0]["video_url"]
    assert "owned-image/content?" in payloads[0]["image_url"]
