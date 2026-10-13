import socket
import time

import pytest
from conftest import graph

from genjutsu.schemas import Graph
from genjutsu.security import allowed_remote, sign_asset, valid_asset_signature


def test_provider_allowlist_and_private_dns_rejected(settings, monkeypatch):
    settings.testing = False
    settings.download_hosts = ["cdn.example"]
    openrouter = "https://openrouter.ai/api/v1/videos"
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(ValueError):
        allowed_remote(openrouter, settings)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    assert allowed_remote(openrouter, settings)
    for url in [
        "https://unapproved.example/v1",
        "http://openrouter.ai/api/v1",
        "https://user:secret@openrouter.ai/api/v1",
    ]:
        with pytest.raises(ValueError):
            allowed_remote(url, settings)
    assert allowed_remote("https://cdn.example/result.mp4", settings, download=True)
    with pytest.raises(ValueError):
        allowed_remote(
            "https://cdn.example.evil.example/r.mp4", settings, download=True
        )


def test_signed_asset_expiry(settings):
    expiry = int(time.time()) - 1
    assert not valid_asset_signature(
        settings.secret_key,
        "asset",
        expiry,
        sign_asset(settings.secret_key, "asset", expiry),
    )
    expiry = int(time.time()) + 60
    assert valid_asset_signature(
        settings.secret_key,
        "asset",
        expiry,
        sign_asset(settings.secret_key, "asset", expiry),
    )
    assert not valid_asset_signature(
        settings.secret_key,
        "other",
        expiry,
        sign_asset(settings.secret_key, "asset", expiry),
    )


def test_graph_rejects_nonfinite_positions_and_embedded_credentials():
    g = graph()
    g["nodes"][0]["position"]["x"] = float("nan")
    with pytest.raises(ValueError):
        Graph.model_validate(g)
    g = graph()
    g["nodes"][0]["data"]["providerInput"] = {"api_key": "hidden"}
    with pytest.raises(ValueError):
        Graph.model_validate(g)
