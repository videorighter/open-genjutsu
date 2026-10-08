import pytest
from fastapi.testclient import TestClient

from genjutsu.model_catalog import input_errors
from genjutsu.schemas import NodeData


def data(model, inputs, kind="motion"):
    return NodeData(
        kind=kind,
        label="model",
        provider="fal",
        model=model,
        prompt="",
        temperature=0.7,
        seed="42",
        resolution="720p",
        providerInput=inputs,
    )


@pytest.mark.parametrize(
    "inputs",
    [
        {"character_orientation": "sideways"},
        {"keep_original_sound": "false"},
    ],
)
def test_kling_rejects_invalid_typed_inputs(inputs):
    assert input_errors(data("fal-ai/kling-video/v3/pro/motion-control", inputs))


@pytest.mark.parametrize(
    "inputs",
    [
        {"num_inference_steps": 51},
        {"num_inference_steps": True},
        {"guidance_scale": 0},
        {"mask_video_url": "http://example.com/mask.mp4"},
        {"mask_image_url": "https://user:pass@example.com/mask.png"},
    ],
)
def test_vace_rejects_invalid_parameters(inputs):
    assert input_errors(data("fal-ai/wan-vace-14b", inputs))


def test_vace_allows_bounded_inputs_and_placeholders():
    assert not input_errors(
        data(
            "fal-ai/wan-vace-14b",
            {
                "task": "inpainting",
                "num_inference_steps": 30,
                "guidance_scale": 5.5,
                "mask_image_url": "$image",
            },
        )
    )


def test_custom_model_remains_configurable():
    assert not input_errors(data("my/model", {"my_option": "value"}))


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
