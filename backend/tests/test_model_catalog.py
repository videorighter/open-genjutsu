from fastapi.testclient import TestClient

from genjutsu.model_catalog import CATALOG, input_errors
from genjutsu.schemas import NodeData


def data(model, inputs, kind="motion", provider="openrouter", **extra):
    return NodeData(
        kind=kind,
        label="model",
        provider=provider,
        model=model,
        prompt="Keep the motion.",
        temperature=0.7,
        seed="42",
        resolution="720p",
        providerInput=inputs,
        **extra,
    )


def test_catalog_offers_only_openrouter_with_a_default_per_generation_step():
    # Generation runs on OpenRouter only; Local is just the FFmpeg 결과 내보내기.
    local = [m for m in CATALOG["models"] if m["provider"] == "local"]
    assert [(m["id"], m["kinds"]) for m in local] == [("ffmpeg", ["output"])]
    assert {m["provider"] for m in CATALOG["models"]} == {"openrouter", "local"}
    ids = {m["id"]: m["kinds"] for m in CATALOG["models"]}
    for kind, model in CATALOG["defaults"].items():
        assert kind in ids[model]
    assert sum("motion" in kinds for kinds in ids.values()) >= 8


def test_removed_provider_nodes_open_with_openrouter_defaults():
    node = data(
        "fal-ai/wan/v2.2-14b/animate/move",
        {"character_orientation": "video"},
        provider="fal",
        endpoint="https://models.example.com/v1",
    )
    assert (node.provider, node.model, node.providerInput) == (
        "openrouter",
        "minimax/hailuo-3",
        {},
    )
    assert node.prompt == "Keep the motion."


def test_curated_parameters_are_type_checked():
    model = "cognitivecomputations/dolphin-mistral-24b-venice-edition"
    assert input_errors(data(model, {"max_tokens": 0}, kind="prompt"))
    assert input_errors(data(model, {"max_tokens": True}, kind="prompt"))
    assert not input_errors(data(model, {"max_tokens": 512}, kind="prompt"))


def test_catalog_needs_login_and_preserves_verification_status(app, client):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/models").status_code == 401
    catalog = client.get("/api/models").json()
    assert all(
        not m["generationVerified"]
        for m in catalog["models"]
        if m["provider"] != "local"
    )


def test_operations_are_admin_only_and_have_no_prompt_or_key(client, app):
    result = client.get("/api/admin/operations")
    assert result.status_code == 200
    assert result.json()["recent_completed_samples"] == 0
    assert result.json()["recent_p95_seconds"] is None
    assert result.json()["disk_free_bytes"] > 0
    assert client.get("/api/admin/jobs/review").json() == []
    assert (
        client.post(
            "/api/admin/users",
            json={"email": "operator-test@test.local", "password": "test-password-123"},
        ).status_code
        == 201
    )
    with TestClient(app) as other:
        assert (
            other.post(
                "/api/auth/login",
                json={
                    "email": "operator-test@test.local",
                    "password": "test-password-123",
                },
            ).status_code
            == 200
        )
        assert other.get("/api/admin/operations").status_code == 403
        assert other.get("/api/admin/jobs/review").status_code == 403
