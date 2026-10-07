import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from genjutsu.api import create_app
from genjutsu.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        secret_key="test-secret-key-only-12345678901234567890",
        admin_email="admin@test.local",
        admin_password="test-password-123",
        secure_cookies=False,
        testing=True,
        temporal_enabled=False,
        database_url=f"sqlite:///{tmp_path}/test.db",
        data_dir=tmp_path,
        static_dir=tmp_path / "no-web",
    )


@pytest.fixture
def app(settings):
    return create_app(settings, dispatch=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        r = c.post(
            "/api/auth/login",
            json={"email": "admin@test.local", "password": "test-password-123"},
        )
        assert r.status_code == 200
        c.headers["X-CSRF-Token"] = c.cookies["genjutsu_csrf"]
        yield c


@pytest.fixture
def image():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(out, "PNG")
    return out.getvalue()


def graph(asset_id=None):
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
                **({"assetId": asset_id} if asset_id and kind == "video" else {}),
            },
        }

    return {
        "version": 1,
        "title": "Test service",
        "nodes": [node("video", "video", 0), node("output", "output", 300)],
        "edges": [
            {"id": "e", "source": "video", "target": "output", "type": "smoothstep"}
        ],
    }
