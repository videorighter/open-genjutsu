import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from genjutsu import model_catalog
from genjutsu.db import Asset, User
from genjutsu.schemas import Graph, NodeData
from genjutsu.validation import validate_execution

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/openrouter_catalog.json").read_text()
)
LIVE = model_catalog.normalize_openrouter(
    FIXTURE["models"], FIXTURE["videos"], FIXTURE["images"]
)
GROK = "x-ai/grok-imagine-video-1.5-lite"
SEEDANCE = "bytedance/seedance-2.0-mini"
HAILUO = "minimax/hailuo-3"
QWEN_VL = "qwen/qwen3-vl-30b-a3b-instruct"
DOLPHIN = "cognitivecomputations/dolphin-mistral-24b-venice-edition"
LING = "inclusionai/ling-3.0-flash-vl"
QWEN_IMAGE = "qwen/qwen-image-3"


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setitem(model_catalog._live, "models", LIVE)
    return LIVE


def test_contracts_follow_openrouter_capabilities():
    assert LIVE[DOLPHIN]["kinds"] == ["prompt"]
    assert LIVE[QWEN_VL]["kinds"] == ["prompt", "analysis"]
    assert LIVE["qwen/qwen-image-3"]["kinds"] == ["image"]
    grok = {p["key"]: p for p in LIVE[GROK]["parameters"]}
    assert set(grok) == {"resolution", "duration", "aspect_ratio", "image_mode"}
    assert grok["duration"]["options"][0] == 1 and grok["duration"]["default"] == 5
    assert grok["image_mode"]["options"] == ["first_frame", "reference"]
    assert "video" in LIVE[SEEDANCE]["inputs"]
    assert "video" not in LIVE[GROK]["inputs"]


def test_estimate_matches_observed_openrouter_charge():
    # Probe 2026-10-12: 1s 480p cost $0.02, plus one first-frame image $0.03.
    def data(inputs):
        return NodeData(
            kind="motion", label="m", provider="openrouter", model=GROK,
            providerInput=inputs,
        )  # fmt: skip

    one_second = {"resolution": "480p", "duration": 1}
    assert model_catalog.estimate_usd(data(one_second), LIVE[GROK], 0) == 0.02
    assert model_catalog.estimate_usd(data(one_second), LIVE[GROK], 1) == 0.03
    assert model_catalog.estimate_usd(data({}), LIVE[SEEDANCE], 0) is None
    # Real run 2026-10-13: MiniMax H3, 5s with one reference image, billed $0.65.
    assert model_catalog.estimate_usd(data({}), LIVE[HAILUO], 1) == 0.65


@pytest.mark.parametrize(
    "sku, inputs, images, usd",
    [
        ({"duration_seconds_480p": "0.05", "duration_seconds_720p": "0.1"},
         {"resolution": "720p"}, 0, 0.5),  # Wan 3.0
        ({"duration_seconds": "0.112", "image_to_video_duration_seconds_720p": "0.112",
          "text_to_video_duration_seconds_720p": "0.084"},
         {"resolution": "720p"}, 0, 0.42),  # Kling v3.0 Pro, text only
        ({"duration_seconds_with_audio": "0.40", "duration_seconds_without_audio": "0.20",
          "duration_seconds_without_audio_4k": "0.40"},
         {"resolution": "4K"}, 1, 2.0),  # Veo 3.1 at 4K, audio off
        ({"cents_per_second_output": "17", "cents_per_second_output_1080p": "29"},
         {"resolution": "1080p"}, 0, 1.45),  # FLUX.3 Video
        ({"video_tokens": "0.0000107"}, {"resolution": "720p"}, 0, None),  # Seedance
    ],
)  # fmt: skip
def test_estimate_reads_dollar_and_resolution_skus(sku, inputs, images, usd):
    contract = {"outputs": ["video"], "pricing": sku, "parameters": [
        {"key": "resolution", "default": "720p"}, {"key": "duration", "default": 5}]}  # fmt: skip
    data = NodeData(kind="motion", label="m", provider="openrouter", model="x/y",
                    providerInput=inputs)  # fmt: skip
    assert model_catalog.estimate_usd(data, contract, images) == usd


def test_refresh_failure_keeps_last_catalog(settings, monkeypatch, live):
    def offline(settings):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(model_catalog, "fetch_openrouter", offline)
    monkeypatch.setitem(model_catalog._live, "fetched", 0.0)
    monkeypatch.setitem(model_catalog._live, "attempted", 0.0)
    monkeypatch.setattr(settings, "testing", False)
    assert model_catalog.openrouter_models(settings, refresh=True) is LIVE


def validate(
    app, settings, step, inputs=None, sources=("video",), data=None, video_size=10,
    **overrides,
):  # fmt: skip
    with app.state.database.session.begin() as db:
        user = db.scalar(select(User))
        assets = {
            kind: Asset(
                user_id=user.id,
                filename=kind,
                mime=mime,
                size=video_size if kind == "video" else 10,
                checksum="a" * 64,
                metadata_json={"duration": 3},
            )  # fmt: skip
            for kind, mime in [("video", "video/mp4"), ("reference", "image/png")]
        }
        db.add_all(assets.values())
        db.flush()

        def node(id, kind, provider, model, **data):
            return {
                "id": id,
                "position": {"x": 0, "y": 0},
                "data": {"kind": kind, "label": id, "provider": provider,
                         "model": model, **data},
            }  # fmt: skip

        nodes = [
            node(k, k, "local", "media-input", assetId=a.id) for k, a in assets.items()
        ]
        extra = {
            "provider": "openrouter",
            "providerInput": inputs or {},
            **(data or {}),
        }
        nodes += [
            node("step", step[0], extra.pop("provider"), step[1], **extra),
            node("output", "output", "local", "ffmpeg"),
        ]
        edges = [{"id": s, "source": s, "target": "step"} for s in sources]
        edges.append({"id": "out", "source": "video", "target": "output"})
        graph = Graph.model_validate(
            {"version": 1, "title": "t", "nodes": nodes, "edges": edges}
        )
        return validate_execution(
            graph, db, user.id, settings.model_copy(update=overrides)
        )


def test_text_steps_warn_without_catalog_and_reject_unknown_models(
    app, client, settings, monkeypatch
):
    monkeypatch.setitem(model_catalog._live, "models", None)
    result = validate(app, settings, ("analysis", QWEN_VL))
    assert any("목록을 확인하지" in w for w in result["warnings"])
    monkeypatch.setitem(model_catalog._live, "models", LIVE)
    assert not validate(app, settings, ("analysis", QWEN_VL))["warnings"]
    assert any(
        "찾을 수 없는" in e
        for e in validate(app, settings, ("analysis", "gone/model"))["errors"]
    )
    assert any(
        "장면 분석 노드를 지원하지" in e
        for e in validate(app, settings, ("analysis", DOLPHIN))["errors"]
    )


def test_video_step_without_catalog_fails_closed(app, client, settings, monkeypatch):
    monkeypatch.setitem(model_catalog._live, "models", None)
    errors = validate(app, settings, ("motion", GROK))["errors"]
    assert any("목록을 확인하지" in e for e in errors)


@pytest.mark.parametrize(
    "model, inputs, sources, expected",
    [
        (GROK, {}, ("video",), "연결된 영상을 반영하지"),
        (GROK, {"duration": True}, ("reference",), "입력 형식 또는 범위"),
        (GROK, {"resolution": "4K"}, ("reference",), "입력 형식 또는 범위"),
        (GROK, {"motion_strength": 1}, ("reference",), "motion_strength"),
        (GROK, {"image_mode": "first_last"}, ("reference",), "입력 형식 또는 범위"),
        (SEEDANCE, {"image_mode": "first_last"}, ("reference",), "참조 이미지 2개"),
    ],
)
def test_video_step_checks_model_capabilities(
    app, client, settings, live, model, inputs, sources, expected
):
    errors = validate(app, settings, ("motion", model), inputs, sources)["errors"]
    assert any(expected in e for e in errors), errors


def test_video_reference_needs_https_outside_tests(app, client, settings, live):
    errors = validate(
        app, settings, ("motion", SEEDANCE), sources=("video", "reference"),
        testing=False,
    )["errors"]  # fmt: skip
    assert any("HTTPS" in e for e in errors)


def test_preflight_reports_cost_estimate(app, client, settings, live):
    result = validate(
        app, settings, ("motion", GROK), {"resolution": "480p", "duration": 1},
        sources=("reference",),
    )  # fmt: skip
    assert result["estimated_cost_usd"] == 0.03
    assert result["unestimated_steps"] == 0


def test_models_api_lists_live_openrouter_contracts(client, live):
    catalog = client.get("/api/models").json()
    assert catalog["openrouter"]["available"]
    assert {m["id"] for m in catalog["openrouter"]["models"]} == set(LIVE)
    assert catalog["models"]  # Curated recommendations stay available.


def test_video_input_and_image_models_get_their_own_settings():
    ling = {p["key"]: p for p in LIVE[LING]["parameters"]}
    assert ling["analysis_input"]["options"] == ["frames", "video"]
    assert "analysis_input" not in {p["key"] for p in LIVE[QWEN_VL]["parameters"]}
    assert LIVE[QWEN_IMAGE]["kinds"] == ["image"]
    assert [p["key"] for p in LIVE[QWEN_IMAGE]["parameters"]] == ["aspect_ratio"]


def test_image_step_needs_openrouter_and_a_direction(app, client, settings, live):
    errors = validate(app, settings, ("image", QWEN_IMAGE), sources=("reference",))[
        "errors"
    ]
    assert any("이미지를 설명하는 지시" in e for e in errors)
    errors = validate(
        app, settings, ("image", QWEN_IMAGE), sources=("reference",),
        data={"provider": "local", "prompt": "hero"},
    )["errors"]  # fmt: skip
    assert any("생성 노드는 OpenRouter" in e for e in errors)
    errors = validate(
        app, settings, ("image", QWEN_VL), sources=("reference",),
        data={"prompt": "hero"},
    )["errors"]  # fmt: skip
    assert any("이미지 생성 노드를 지원하지" in e for e in errors)


def test_inline_video_analysis_is_size_limited_without_https(
    app, client, settings, live
):
    big = 25 * 1024 * 1024
    args = (app, settings, ("analysis", LING), {"analysis_input": "video"})
    assert any(
        "직접 분석할 수 없습니다" in e
        for e in validate(*args, video_size=big)["errors"]
    )
    assert not any("직접 분석" in e for e in validate(*args)["errors"])
    assert not any(
        "직접 분석" in e
        for e in validate(
            *args, video_size=big, public_url="https://studio.example.com"
        )["errors"]
    )


def test_analysis_input_video_needs_a_video_capable_model(app, client, settings, live):
    errors = validate(
        app, settings, ("analysis", QWEN_VL), {"analysis_input": "video"}
    )["errors"]
    assert any("영상 전체 분석을 지원하지" in e for e in errors)


def test_preflight_checks_the_pinned_snapshot(client, image, live, monkeypatch):
    only_last = json.loads(json.dumps(LIVE[SEEDANCE])) | {"id": "x/only-last"}
    for p in only_last["parameters"]:
        if p["key"] == "image_mode":
            p.update(options=["first_last"], default="first_last")
    monkeypatch.setitem(
        model_catalog._live, "models", {**LIVE, "x/only-last": only_last}
    )
    ref = client.post("/api/assets", files={"file": ("r.png", image, "image/png")})
    nodes = [
        {"id": "ref", "position": {"x": 0, "y": 0}, "data": {"kind": "reference",
         "label": "ref", "provider": "local", "model": "media-input",
         "assetId": ref.json()["id"]}},
        {"id": "m", "position": {"x": 0, "y": 0}, "data": {"kind": "motion",
         "label": "m", "provider": "openrouter", "model": "x/only-last"}},
        {"id": "out", "position": {"x": 0, "y": 0}, "data": {"kind": "output",
         "label": "out", "provider": "local", "model": "ffmpeg"}},
    ]  # fmt: skip
    edges = [{"id": "a", "source": "ref", "target": "m"},
             {"id": "b", "source": "m", "target": "out"}]  # fmt: skip
    graph = {"version": 1, "title": "t", "nodes": nodes, "edges": edges}
    w = client.post("/api/workflows", json={"revision": 0, "graph": graph}).json()
    errors = client.post(f"/api/workflows/{w['id']}/validate").json()["errors"]
    assert any("참조 이미지 2개" in e for e in errors)


def test_reconcile_resumes_only_video_steps_with_their_own_ticket(app, client, live):
    from datetime import timedelta

    from genjutsu.db import Job, Step, WorkflowRecord, now

    def node(id, kind, model):
        return {"id": id, "position": {"x": 0, "y": 0}, "data": {"kind": kind,
                "label": id, "provider": "openrouter", "model": model}}  # fmt: skip

    with app.state.database.session.begin() as db:
        user = db.scalar(select(User))
        graph = {"version": 1, "title": "t", "edges": [],
                 "nodes": [node("motion", "motion", GROK), node("hero", "image", QWEN_IMAGE)]}  # fmt: skip
        w = WorkflowRecord(user_id=user.id, title="t", graph=graph)
        db.add(w)
        db.flush()
        job = Job(user_id=user.id, workflow_id=w.id, request_key="k" * 8,
                  request_hash="h", graph=graph, status="NEEDS_REVIEW",
                  updated=now() - timedelta(minutes=10))  # fmt: skip
        db.add(job)
        db.flush()
        db.add_all([
            Step(job_id=job.id, node_id="motion", status="SUBMITTED",
                 provider_id="gen-vid-1-abc", ticket={"status_url": "x"}),
            Step(job_id=job.id, node_id="hero", status="UNKNOWN"),
        ])  # fmt: skip
        id = job.id

    def reconcile(node_id, provider_id):
        return client.post(
            f"/api/admin/jobs/{id}/reconcile",
            json={"node_id": node_id, "provider_id": provider_id},
        ).status_code

    assert reconcile("hero", "gen-vid-9-zzz") == 422  # Images have no async ID.
    assert reconcile("motion", "gen-vid-2-other") == 422  # Cannot swap a known ticket.
    assert reconcile("motion", "gen-vid-1-abc") == 200
    with app.state.database.session() as db:
        step = db.scalar(
            select(Step).where(Step.job_id == id, Step.node_id == "motion")
        )
        assert step.status == "SUBMITTED"
        assert step.ticket["result_url"].endswith(
            "/videos/gen-vid-1-abc/content?index=0"
        )


def test_projects_saved_with_removed_providers_run_openrouter_defaults(
    app, client, image, live
):
    from genjutsu.db import Job, WorkflowRecord

    ref = client.post("/api/assets", files={"file": ("r.png", image, "image/png")})
    client.put("/api/credentials/openrouter", json={"key": "fake-key-123"})
    nodes = [
        {"id": "ref", "position": {"x": 0, "y": 0}, "data": {"kind": "reference",
         "label": "ref", "provider": "local", "model": "media-input",
         "assetId": ref.json()["id"]}},
        {"id": "m", "position": {"x": 0, "y": 0}, "data": {"kind": "motion",
         "label": "m", "provider": "fal", "model": "fal-ai/wan/v2.2-14b/animate/move",
         "endpoint": "https://models.example.com/v1",
         "providerInput": {"character_orientation": "video"}}},
        {"id": "out", "position": {"x": 0, "y": 0}, "data": {"kind": "output",
         "label": "out", "provider": "local", "model": "ffmpeg"}},
    ]  # fmt: skip
    edges = [{"id": "a", "source": "ref", "target": "m"},
             {"id": "b", "source": "m", "target": "out"}]  # fmt: skip
    with app.state.database.session.begin() as db:
        user = db.scalar(select(User))
        # Stored before this release: never re-saved through the current schema.
        w = WorkflowRecord(user_id=user.id, title="t", graph={"version": 1,
                           "title": "t", "nodes": nodes, "edges": edges})  # fmt: skip
        db.add(w)
        db.flush()
        id, revision = w.id, w.revision
    assert client.post(f"/api/workflows/{id}/validate").json()["errors"] == []
    job = client.post(f"/api/workflows/{id}/jobs", json={"revision": revision,
                      "request_key": "legacy-1", "confirm_paid": True})  # fmt: skip
    assert job.status_code == 202, job.text
    with app.state.database.session() as db:
        motion = next(
            n["data"] for n in db.get(Job, job.json()["id"]).graph["nodes"]
            if n["id"] == "m"
        )  # fmt: skip
    assert (motion["provider"], motion["model"]) == (
        "openrouter",
        HAILUO,
    )
    assert (
        "endpoint" not in motion
        and "character_orientation" not in motion["providerInput"]
    )
    # The live contract's defaults are pinned, as for any new OpenRouter step.
    assert motion["providerInput"]["resolution"] == "2K"
    assert motion["providerInput"]["duration"] == 5
