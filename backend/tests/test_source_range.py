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

    def run(clip=None, seconds=10, takes_video=True, mode="first_frame"):
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
                      "providerInput": {"image_mode": mode, "duration": 15}},
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
            motion = next(n for n in pinned["nodes"] if n["id"] == "m")["data"]
            check["chunks"] = motion.get("chunks")
            return motion["providerInput"]["duration"], check

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


def test_a_range_longer_than_the_model_is_split_into_equal_chunks(plan):
    # H3 takes up to 15 s: 21 s becomes two 10.5 s 조각, each generated as 11 s.
    duration, check = plan(seconds=21, mode="reference")
    assert (duration, check["chunks"], check["estimated_cost_usd"]) == (11, 2, 2.86)
    assert check["warnings"] == [
        "m: 구간 21.0초를 조각 2개(10.5초씩)로 나눠 차례로 생성하고 이어 붙입니다. 비용은 조각마다 11초 기준이고, 시간은 조각 수만큼 걸립니다(MiniMax H3는 8초 조각에 약 10분)."
    ]
    assert not [e for e in check["errors"] if "구간" in e]
    # 90 s → six 15 s 조각; without reference images the 조각 are not linked.
    duration, check = plan(seconds=90)
    assert (duration, check["chunks"]) == (15, 6)
    assert "앞 조각의 마지막 프레임" in check["warnings"][1]
    assert plan(seconds=15)[1]["chunks"] is None


def test_range_must_fit_the_video(plan):
    for clip in [{"start": 8, "end": 12}, {"start": 5, "end": 5}]:
        assert [e for e in plan(clip=clip)[1]["errors"] if "구간" in e] == [
            "v: 구간은 0~10.0초 안에서 시작이 끝보다 앞서야 합니다."
        ]
