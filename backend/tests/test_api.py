import json
import time

from conftest import graph
from fastapi.testclient import TestClient
from sqlalchemy import select

from genjutsu.db import Asset, Credential, User
from genjutsu.security import sign_asset


def test_session_cookie_csrf_and_logout(app, client):
    assert client.get("/api/auth/me").status_code == 200
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/session").json() == {"user": None}


def test_login_throttled_and_secrets_not_reflected(app):
    with TestClient(app) as c:
        for _ in range(10):
            assert (
                c.post(
                    "/api/auth/login",
                    json={"email": "nobody@test.local", "password": "wrong"},
                ).status_code
                == 401
            )
        assert (
            c.post(
                "/api/auth/login",
                json={"email": "nobody@test.local", "password": "wrong"},
            ).status_code
            == 429
        )
        r = c.put("/api/credentials/fal", json={"key": "123"})
        assert "123" not in r.text


def test_foreign_origin_blocked(client):
    assert (
        client.post(
            "/api/auth/logout", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_workflow_revision_and_invalid_graph(client):
    r = client.post("/api/workflows", json={"revision": 0, "graph": graph()})
    assert r.status_code == 201
    w = r.json()
    r = client.put("/api/workflows/" + w["id"], json={"revision": 1, "graph": graph()})
    assert r.json()["revision"] == 2
    assert (
        client.put(
            "/api/workflows/" + w["id"], json={"revision": 1, "graph": graph()}
        ).status_code
        == 409
    )
    bad = graph()
    bad["nodes"].append(bad["nodes"][0])
    assert (
        client.post("/api/workflows", json={"revision": 0, "graph": bad}).status_code
        == 422
    )
    bad = graph()
    bad["edges"].append({"id": "cycle", "source": "output", "target": "video"})
    assert (
        client.post("/api/workflows", json={"revision": 0, "graph": bad}).status_code
        == 422
    )


def test_keys_encrypted_and_never_returned(client, app):
    secret = "fake-provider-key-abcdefgh"
    assert client.put("/api/credentials/fal", json={"key": secret}).status_code == 200
    assert client.get("/api/credentials").json() == {"providers": ["fal"]}
    with app.state.database.session() as db:
        c = db.scalar(select(Credential))
        assert secret not in c.encrypted_key
    assert secret not in client.get("/api/credentials").text


def test_uploaded_media_is_validated_owned_and_signed(client, app, image, settings):
    bad = client.post(
        "/api/assets",
        files={"file": ("fake.png", b"<script>evil</script>", "image/png")},
    )
    assert bad.status_code == 422
    r = client.post(
        "/api/assets", files={"file": ("reference.png", image, "text/plain")}
    )
    assert r.status_code == 201
    id = r.json()["id"]
    assert r.json()["mime"] == "image/png"
    assert client.get(f"/api/assets/{id}/content").content == image
    with TestClient(app) as stranger:
        assert stranger.get(f"/api/assets/{id}/content").status_code == 401
        expiry = int(time.time()) + 60
        sig = sign_asset(settings.secret_key, id, expiry)
        assert (
            stranger.get(
                f"/api/assets/{id}/content?expires={expiry}&token={sig}"
            ).status_code
            == 200
        )
        assert (
            stranger.get(
                f"/api/assets/{id}/content?expires={expiry}&token=invalid"
            ).status_code
            == 401
        )


def test_tenant_isolation(client, app, image):
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph()}).json()
    a = client.post("/api/assets", files={"file": ("a.png", image, "image/png")}).json()
    assert (
        client.post(
            "/api/admin/users",
            json={"email": "other@test.local", "password": "other-password-123"},
        ).status_code
        == 201
    )
    with TestClient(app) as other:
        other.post(
            "/api/auth/login",
            json={"email": "other@test.local", "password": "other-password-123"},
        )
        other.headers["X-CSRF-Token"] = other.cookies["genjutsu_csrf"]
        assert other.get("/api/workflows").json() == []
        assert (
            other.put(
                "/api/workflows/" + w["id"], json={"revision": 1, "graph": graph()}
            ).status_code
            == 404
        )
        assert other.get(f"/api/assets/{a['id']}/content").status_code == 404
        assert (
            other.post(
                "/api/admin/users",
                json={"email": "bad@test.local", "password": "bad-password-123"},
            ).status_code
            == 403
        )


def test_missing_media_blocks_submission(client):
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph()}).json()
    assert client.post(f"/api/workflows/{w['id']}/validate").json()["errors"]
    assert (
        client.post(
            f"/api/workflows/{w['id']}/jobs",
            json={"revision": 1, "request_key": "stable-request-1"},
        ).status_code
        == 422
    )


def test_idempotent_submission_quota_cancel_and_key_rotation(client, app):
    with app.state.database.session.begin() as db:
        u = db.scalar(select(User))
        a = Asset(
            user_id=u.id,
            filename="a.mp4",
            mime="video/mp4",
            size=10,
            checksum="0" * 64,
            metadata_json={"duration": 1},
        )
        db.add(a)
        db.flush()
        id = a.id
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph(id)}).json()
    path = f"/api/workflows/{w['id']}/jobs"
    body = {"revision": 1, "request_key": "stable-request-1"}
    a = client.post(path, json=body)
    assert a.status_code == 202
    b = client.post(path, json=body)
    assert a.json()["id"] == b.json()["id"]
    assert (
        client.put("/api/credentials/fal", json={"key": "blocked-key-123"}).status_code
        == 409
    )
    assert (
        client.post(path, json={**body, "request_key": "stable-request-2"}).status_code
        == 202
    )
    assert (
        client.post(path, json={**body, "request_key": "stable-request-3"}).status_code
        == 409
    )
    assert (
        client.post("/api/jobs/" + a.json()["id"] + "/cancel").json()["status"]
        == "CANCELLED"
    )
    assert (
        client.post(path, json={**body, "request_key": "stable-request-3"}).status_code
        == 202
    )


def test_paid_confirmation_required(client, app):

    with app.state.database.session.begin() as db:
        u = db.scalar(select(User))
        a = Asset(
            user_id=u.id,
            filename="a.mp4",
            mime="video/mp4",
            size=10,
            checksum="0" * 64,
            metadata_json={"duration": 1},
        )
        db.add(a)
        db.flush()
        id = a.id
    g = graph(id)
    n = json.loads(json.dumps(g["nodes"][1]))
    n["id"] = "generate"
    n["data"].update(
        kind="motion",
        provider="replicate",
        model="owner/model",
        providerInput={"video": "$video"},
    )
    g["nodes"].insert(1, n)
    g["edges"] = [
        {"id": "a", "source": "video", "target": "generate"},
        {"id": "b", "source": "generate", "target": "output"},
    ]
    client.put("/api/credentials/replicate", json={"key": "fake-key-123"})
    w = client.post("/api/workflows", json={"revision": 0, "graph": g}).json()
    path = f"/api/workflows/{w['id']}/jobs"
    body = {"revision": 1, "request_key": "stable-request-1"}
    assert client.post(path, json=body).status_code == 422
    assert client.post(path, json={**body, "confirm_paid": True}).status_code == 202


def test_chunked_request_body_is_bounded(client):
    def oversized():
        yield b'{"graph":"'
        for _ in range(4):
            yield b"x" * (700_000)
        yield b'"}'

    response = client.post(
        "/api/workflows",
        content=oversized(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413, response.text


def test_custom_keys_are_scoped_to_endpoint(client, app, settings):
    settings.custom_api_urls = ["https://one.example/v1", "https://two.example/v1"]
    assert (
        client.put(
            "/api/credentials/custom",
            json={"key": "fake-key-one", "endpoint": "https://one.example/v1"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/credentials/custom",
            json={"key": "fake-key-two", "endpoint": "https://two.example/v1"},
        ).status_code
        == 200
    )
    from genjutsu.providers import Rejected, credential

    with app.state.database.session() as db:
        u = db.scalar(select(User))
        assert (
            credential(db, u.id, "custom", settings, "https://one.example/v1")
            == "fake-key-one"
        )
        assert (
            credential(db, u.id, "custom", settings, "https://two.example/v1")
            == "fake-key-two"
        )
        import pytest

        with pytest.raises(Rejected):
            credential(db, u.id, "custom", settings, "https://other.example/v1")
    assert client.delete("/api/credentials/custom").status_code == 200
    assert client.get("/api/credentials").json() == {"providers": []}


def test_operator_can_close_confirmed_ambiguous_job(client, app):
    from datetime import timedelta

    from genjutsu.db import Job, now

    w = client.post("/api/workflows", json={"revision": 0, "graph": graph()}).json()
    with app.state.database.session.begin() as db:
        u = db.scalar(select(User))
        j = Job(
            user_id=u.id,
            workflow_id=w["id"],
            request_key="ambiguous-key",
            request_hash="hash",
            graph=graph(),
            status="NEEDS_REVIEW",
            updated=now() - timedelta(minutes=10),
        )
        db.add(j)
        db.flush()
        id = j.id
    assert (
        client.post(
            f"/api/admin/jobs/{id}/close-review",
            json={"reason": "provider confirmed", "confirm_external_resolved": False},
        ).status_code
        == 422
    )
    result = client.post(
        f"/api/admin/jobs/{id}/close-review",
        json={
            "reason": "provider confirmed no further charges",
            "confirm_external_resolved": True,
        },
    )
    assert result.json()["status"] == "FAILED"
    with app.state.database.session() as db:
        assert "provider confirmed" in db.get(Job, id).review_note


def test_owned_media_and_records_can_be_deleted_safely(client, image):
    a = client.post(
        "/api/assets", files={"file": ("ref.png", image, "image/png")}
    ).json()
    assert client.delete("/api/assets/" + a["id"]).status_code == 200
    assert client.get("/api/assets/" + a["id"] + "/content").status_code == 404
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph()}).json()
    assert client.delete("/api/workflows/" + w["id"]).status_code == 200
    assert client.get("/api/workflows").json() == []
