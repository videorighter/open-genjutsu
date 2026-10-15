import pytest
from sqlalchemy import select
from test_openrouter_catalog import HAILUO, LIVE, SEEDANCE

from genjutsu import model_catalog
from genjutsu.db import Asset, User
from genjutsu.providers import output_audio, upstream_source
from genjutsu.schemas import Graph
from genjutsu.validation import validate_execution


def graph(kinds, edges, data=None):
    return {
        "nodes": [
            {"id": id, "data": {"kind": kind, **(data or {}).get(id, {})}}
            for id, kind in kinds.items()
        ],
        "edges": [{"source": a, "target": b} for a, b in edges],
    }


def test_upstream_source_walks_back_to_the_nearest_source_video():
    g = graph(
        {"far": "video", "ref": "reference", "near": "video", "m": "motion", "out": "output"},
        [("far", "m"), ("ref", "m"), ("m", "out")],
    )  # fmt: skip
    assert upstream_source(g, "out") == "far"
    # A source video that does not feed this output is ignored.
    assert upstream_source(g, "near") is None


def test_unset_audio_follows_the_flow_and_a_choice_wins():
    with_source = graph({"v": "video", "out": "output"}, [("v", "out")])
    images_only = graph(
        {"r": "reference", "m": "motion", "out": "output"}, [("r", "m"), ("m", "out")]
    )
    out = {"id": "out", "data": {}}
    assert output_audio(with_source, out) == "source"
    assert output_audio(images_only, out) == "generated"
    assert output_audio(images_only, {"id": "out", "data": {"providerInput": {"audio": "none"}}}) == "none"  # fmt: skip


@pytest.fixture
def check(app, client, settings, monkeypatch):
    monkeypatch.setitem(model_catalog._live, "models", LIVE)

    def run(nodes, edges):
        with app.state.database.session.begin() as db:
            user = db.scalar(select(User))
            media = {}
            for kind, mime in [("video", "video/mp4"), ("reference", "image/png")]:
                media[kind] = Asset(user_id=user.id, filename=kind, mime=mime, size=10,
                                    checksum="a" * 64, metadata_json={"duration": 3})  # fmt: skip
            db.add_all(media.values())
            db.flush()
            full = []
            for id, (kind, data) in nodes.items():
                provider, model = {
                    "video": ("local", "media-input"),
                    "reference": ("local", "media-input"),
                    "output": ("local", "ffmpeg"),
                }.get(kind, ("openrouter", data.pop("model", HAILUO)))
                if kind in media:
                    data["assetId"] = media[kind].id
                full.append({"id": id, "position": {"x": 0, "y": 0}, "data": {
                    "kind": kind, "label": id, "provider": provider, "model": model, **data}})  # fmt: skip
            g = Graph.model_validate({"version": 1, "title": "t", "nodes": full,
                "edges": [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in edges]})  # fmt: skip
            return validate_execution(g, db, user.id, settings)

    return run


def out_errors(plan):
    return [e for e in plan["errors"] if e.startswith("out:")]


def test_output_takes_exactly_one_image_or_video(check):
    two = check(
        {"v": ("video", {}), "r": ("reference", {}), "out": ("output", {})},
        [("v", "out"), ("r", "out")],
    )
    assert out_errors(two) == [
        "out: 결과 내보내기에는 이미지나 영상 하나만 연결하세요."
    ]
    text = check(
        {"v": ("video", {}), "a": ("analysis", {"model": "qwen/qwen3-vl-30b-a3b-instruct"}),
         "out": ("output", {})},
        [("v", "a"), ("a", "out")],
    )  # fmt: skip
    assert out_errors(text) == ["out: 이미지나 영상을 연결하세요."]
    image = check({"r": ("reference", {}), "out": ("output", {})}, [("r", "out")])
    assert out_errors(image) == []


def test_chosen_source_audio_needs_a_source_video_upstream(check):
    flow = [("r", "m"), ("m", "out")]
    nodes = {"r": ("reference", {}), "m": ("motion", {"providerInput": {"image_mode": "first_frame"}})}  # fmt: skip
    unset = check({**nodes, "out": ("output", {})}, flow)
    assert out_errors(unset) == []
    chosen = check({**nodes, "out": ("output", {"providerInput": {"audio": "source"}})}, flow)  # fmt: skip
    assert out_errors(chosen) == [
        "out: 원본 오디오를 쓰려면 연결 흐름에 원본 영상이 있어야 합니다. 오디오를 생성 오디오나 무음으로 바꾸세요."
    ]
    bad = check({**nodes, "out": ("output", {"providerInput": {"audio": "loud"}})}, flow)  # fmt: skip
    assert "out: 오디오 입력 형식 또는 범위를 확인하세요." in bad["errors"]


def test_audio_choice_warns_when_generated_audio_is_missing_or_wasted(check):
    def warnings(audio, generate):
        inputs = {"image_mode": "reference", "generate_audio": generate}
        plan = check(
            {"v": ("video", {}), "r": ("reference", {}),
             "m": ("motion", {"model": SEEDANCE, "providerInput": inputs}),
             "out": ("output", {"providerInput": {"audio": audio}})},
            [("v", "m"), ("r", "m"), ("m", "out")],
        )  # fmt: skip
        return [w for w in plan["warnings"] if w.startswith("out:")]

    assert warnings("generated", False) == [
        "out: m의 오디오 생성이 꺼져 있어 결과물에 소리가 없습니다."
    ]
    assert warnings("source", True) == [
        "out: m에서 만든 오디오는 결과물에 쓰지 않지만 오디오 생성 비용은 듭니다."
    ]
    assert warnings("generated", True) == warnings("source", False) == []
