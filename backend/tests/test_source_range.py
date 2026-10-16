import pytest
from sqlalchemy import select
from test_openrouter_catalog import HAILUO, LIVE

from genjutsu import model_catalog
from genjutsu.db import Asset, User
from genjutsu.model_catalog import pin_defaults
from genjutsu.providers import source_seconds
from genjutsu.schemas import Graph
from genjutsu.validation import validate_execution


@pytest.fixture
def plan(app, client, settings, monkeypatch):
    """Pin and validate 원본 영상 → 모션 전이(H3, 5–15 s) → 결과 내보내기."""
    monkeypatch.setitem(model_catalog._live, "models", LIVE)

    def run(clip=None, seconds=10, takes_video=True):
        with app.state.database.session.begin() as db:
            user = db.scalar(select(User))
            video = Asset(user_id=user.id, filename="v.mp4", mime="video/mp4", size=10,
                          checksum="a" * 64, metadata_json={"duration": seconds})  # fmt: skip
            image = Asset(user_id=user.id, filename="r.png", mime="image/png", size=10,
                          checksum="a" * 64, metadata_json={})  # fmt: skip
            db.add_all([video, image])
            db.flush()
            local = {"provider": "local", "model": "media-input"}
            nodes = {
                "v": {"kind": "video", **local, "assetId": video.id,
                      **({"range": clip} if clip else {})},
                "r": {"kind": "reference", **local, "assetId": image.id},
                "m": {"kind": "motion", "provider": "openrouter", "model": HAILUO,
                      "providerInput": {"image_mode": "first_frame", "duration": 15}},
                "out": {"kind": "output", "provider": "local", "model": "ffmpeg"},
            }  # fmt: skip
            edges = [("v", "m")] if takes_video else []
            edges += [("r", "m"), ("m", "out")]
            graph = Graph.model_validate({"version": 1, "title": "t",
                "nodes": [{"id": id, "position": {"x": 0, "y": 0},
                           "data": {"label": id, **data}} for id, data in nodes.items()],
                "edges": [{"id": a + b, "source": a, "target": b} for a, b in edges],
            }).model_dump(exclude_none=True)  # fmt: skip
            pinned = pin_defaults(graph, LIVE, source_seconds(graph, db, user.id))
            check = validate_execution(
                Graph.model_validate(pinned), db, user.id, settings, LIVE
            )
            motion = next(n for n in pinned["nodes"] if n["id"] == "m")
            return motion["data"]["providerInput"]["duration"], check

    return run


def test_a_step_that_takes_a_video_generates_its_range(plan):
    duration, check = plan(clip={"start": 3.0, "end": 7.4})
    assert duration == 5 and check["estimated_cost_usd"] == 0.65
    assert check["warnings"] == [
        "m: 구간이 4.4초라 5초로 생성한 뒤 4.4초로 자릅니다. 비용은 5초 기준입니다."
    ]
    # Without a range the whole video is the 구간; frame rounding costs no extra second.
    duration, check = plan(seconds=10.03)
    assert duration == 10 and check["warnings"] == []
    # Image→video steps keep the chosen duration.
    assert plan(takes_video=False)[0] == 15


def test_range_must_fit_the_video_and_the_model(plan):
    def errors(**kw):
        return [e for e in plan(**kw)[1]["errors"] if "구간" in e]

    assert errors(seconds=30) == [
        "m: 구간 30.0초가 이 모델의 최대 길이 15초보다 깁니다. 원본 영상 노드에서 구간을 15초 이하로 정하세요."
    ]
    for clip in [{"start": 8, "end": 12}, {"start": 5, "end": 5}]:
        assert errors(clip=clip) == [
            "v: 구간은 0~10.0초 안에서 시작이 끝보다 앞서야 합니다."
        ]
