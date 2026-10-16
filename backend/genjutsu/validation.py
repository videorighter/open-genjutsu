import re

from sqlalchemy import select

from .db import Asset, Credential
from .model_catalog import (
    contract_for,
    estimate_usd,
    fit_duration,
    input_errors,
    openrouter_models,
)
from .providers import clip_seconds, output_audio, source_seconds, upstream_source


def validate_execution(graph, session, user_id, settings, live=None):
    errors = []
    warnings = []
    paid = []
    if not graph.nodes or not any(n.data.kind == "output" for n in graph.nodes):
        errors.append("결과 내보내기 노드가 필요합니다.")
    if len(graph.nodes) > settings.max_nodes_per_job:
        errors.append(f"실행은 {settings.max_nodes_per_job}개 노드까지 지원합니다.")
    has_key = session.scalar(
        select(Credential.id).where(
            Credential.user_id == user_id,
            Credential.provider == "openrouter",
            Credential.endpoint == "",
        )
    )
    incoming = {
        n.id: [
            next(x for x in graph.nodes if x.id == e.source)
            for e in graph.edges
            if e.target == n.id
        ]
        for n in graph.nodes
    }

    def kinds(n):
        return {x.data.kind for x in incoming[n.id]}

    live = openrouter_models(settings) if live is None else live
    plain = graph.model_dump()
    seconds = source_seconds(plain, session, user_id)
    estimates = []
    for n in graph.ordered():
        d = n.data
        contract = contract_for(d, live)
        errors.extend(input_errors(d, contract))
        if d.provider == "openrouter" and d.kind not in {
            "video",
            "reference",
            "output",
        }:
            if live is None:
                (errors if d.kind in {"motion", "edit", "image"} else warnings).append(
                    f"{d.label}: OpenRouter 모델 목록을 확인하지 못했습니다."
                )
            elif not contract:
                errors.append(
                    f"{d.label}: OpenRouter에서 찾을 수 없는 모델입니다. 모델 ID를 확인하세요."
                )
            elif d.providerInput.get("analysis_input") == "video" and not any(
                p["key"] == "analysis_input" for p in contract["parameters"]
            ):
                errors.append(
                    f"{d.label}: 이 모델은 영상 전체 분석을 지원하지 않습니다."
                )
        if d.seed and (
            not re.fullmatch(r"[0-9]{1,10}", d.seed) or int(d.seed) > 2147483647
        ):
            errors.append(f"{d.label}: seed는 0~2147483647 정수여야 합니다.")
        if not d.model.strip():
            errors.append(f"{d.label}: 모델 ID가 필요합니다.")
        if d.kind in {"video", "reference"}:
            a = session.get(Asset, d.assetId) if d.assetId else None
            if not a or a.user_id != user_id:
                errors.append(f"{d.label}: 미디어를 서버에 업로드하세요.")
            elif not a.mime.startswith("video/" if d.kind == "video" else "image/"):
                errors.append(f"{d.label}: 미디어 종류가 일치하지 않습니다.")
            elif d.range and not (
                d.range.start < d.range.end <= a.metadata_json["duration"] + 0.05
            ):
                errors.append(
                    f"{d.label}: 구간은 0~{a.metadata_json['duration']:.1f}초 안에서 시작이 끝보다 앞서야 합니다."
                )
            if d.provider != "local":
                errors.append(f"{d.label}: 입력 미디어는 Local을 사용하세요.")
            continue
        if not incoming[n.id]:
            errors.append(f"{d.label}: 입력 연결이 필요합니다.")
        if d.kind == "output":
            if d.provider != "local" or d.model != "ffmpeg":
                errors.append(
                    f"{d.label}: 결과 내보내기는 Local / ffmpeg를 사용하세요."
                )
            errors.extend(output_errors(n, incoming[n.id], graph, live, warnings))
            continue
        paid.append(n)
        images = sum(x.data.kind in {"reference", "image"} for x in incoming[n.id])
        estimates.append(estimate_usd(d, contract, images))
        if d.provider != "openrouter":
            errors.append(f"{d.label}: 생성 노드는 OpenRouter 모델을 사용하세요.")
            continue
        if not has_key:
            errors.append(f"{d.label}: OpenRouter API 키를 등록하세요.")
        if d.kind in {"analysis", "prompt"}:
            tokens = d.providerInput.get("max_tokens", 1024)
            if (
                not isinstance(tokens, int)
                or isinstance(tokens, bool)
                or not 1 <= tokens <= 4096
            ):
                errors.append(f"{d.label}: max_tokens는 1~4096 정수여야 합니다.")
            if d.kind == "analysis" and "video" not in kinds(n):
                errors.append(f"{d.label}: 분석할 원본 영상을 연결하세요.")
            if (
                d.providerInput.get("analysis_input") == "video"
                and not settings.public_url.startswith("https://")
                and any(
                    (a := session.get(Asset, x.data.assetId))
                    and a.size > settings.max_inline_media_mb * 1024 * 1024
                    for x in incoming[n.id]
                    if x.data.kind == "video" and x.data.assetId
                )
            ):
                errors.append(
                    f"{d.label}: 영상이 {settings.max_inline_media_mb}MB를 넘어 직접 분석할 수 없습니다. 샘플 프레임 방식을 사용하세요."
                )
        elif d.kind == "image":
            if not d.prompt.strip() and not kinds(n) & {"prompt", "analysis"}:
                errors.append(f"{d.label}: 만들 이미지를 설명하는 지시를 입력하세요.")
        else:
            errors.extend(
                openrouter_video_errors(d, contract, kinds(n), images, settings)
            )
            if length := clip_seconds(plain, n.id, seconds):
                errors.extend(clip_errors(d, contract, length, warnings))
    if len(paid) > settings.max_paid_steps:
        errors.append(f"유료 단계는 최대 {settings.max_paid_steps}개입니다.")
    known = [e for e in estimates if e is not None]
    return {
        "errors": errors,
        "warnings": warnings,
        "paid_steps": len(paid),
        "estimated_cost_usd": round(sum(known), 4) if known else None,
        "unestimated_steps": len(estimates) - len(known),
        "max_active_jobs": settings.max_active_jobs,
    }


def output_errors(n, sources, graph, live, warnings):
    """결과 내보내기 takes one image or video; the audio choice must be satisfiable."""
    d = n.data
    kinds = {x.data.kind for x in sources}
    if len(sources) > 1:
        return [f"{d.label}: 결과 내보내기에는 이미지나 영상 하나만 연결하세요."]
    if not kinds & {"video", "motion", "edit", "reference", "image"}:
        return [f"{d.label}: 이미지나 영상을 연결하세요."]
    if not kinds & {"video", "motion", "edit"}:
        return []  # Images keep their own format; audio does not apply.
    graph = graph.model_dump()
    audio = output_audio(graph, {"id": n.id, "data": d.model_dump()})
    if audio == "source" and not upstream_source(graph, n.id):
        return [
            f"{d.label}: 원본 오디오를 쓰려면 연결 흐름에 원본 영상이 있어야 합니다. 오디오를 생성 오디오나 무음으로 바꾸세요."
        ]
    previous = sources[0].data
    contract = contract_for(previous, live)
    if previous.kind in {"motion", "edit"} and contract:
        option = next(
            (p for p in contract["parameters"] if p["key"] == "generate_audio"), None
        )
        on = option and previous.providerInput.get("generate_audio", option["default"])
        if audio == "generated" and option and not on:
            warnings.append(
                f"{d.label}: {previous.label}의 오디오 생성이 꺼져 있어 결과물에 소리가 없습니다."
            )
        if audio != "generated" and on:
            warnings.append(
                f"{d.label}: {previous.label}에서 만든 오디오는 결과물에 쓰지 않지만 오디오 생성 비용은 듭니다."
            )
    return []


def clip_errors(d, contract, length, warnings):
    """A step that takes a video generates its 구간: the shortest allowed duration, cut down."""
    if not contract or "video" not in contract.get("outputs", []):
        return []
    options = next(
        (p["options"] for p in contract["parameters"] if p["key"] == "duration"), []
    )
    fit = fit_duration(contract, length)
    if options and fit is None:
        return [
            f"{d.label}: 구간 {length:.1f}초가 이 모델의 최대 길이 {max(options)}초보다 깁니다. 원본 영상 노드에서 구간을 {max(options)}초 이하로 정하세요."
        ]
    if fit and fit > round(length, 1):
        warnings.append(
            f"{d.label}: 구간이 {length:.1f}초라 {fit}초로 생성한 뒤 {length:.1f}초로 자릅니다. 비용은 {fit}초 기준입니다."
        )
    return []


def openrouter_video_errors(d, contract, sources, images, settings):
    if not contract or "video" not in contract.get("outputs", []):
        return []  # Missing models and wrong kinds are reported above.
    errors = []
    allowed = {p["key"] for p in contract["parameters"]}
    if unknown := sorted(set(d.providerInput) - allowed):
        errors.append(
            f"{d.label}: 이 모델에서 지원하지 않는 입력 항목입니다: {', '.join(unknown)}"
        )
    if sources & {"video", "motion", "edit"}:
        if "video" not in contract["inputs"]:
            errors.append(
                f"{d.label}: 이 모델은 연결된 영상을 반영하지 않습니다. 영상을 받는 모델을 선택하세요."
            )
        elif not settings.testing and not settings.public_url.startswith("https://"):
            # OpenRouter accepts only HTTPS video references (data URLs are rejected).
            errors.append(
                f"{d.label}: 원본 영상을 모델에 보내려면 공급자가 접근할 수 있는 HTTPS 서비스 주소가 필요합니다. 공개 HTTPS 주소(예: Cloudflare Tunnel)로 서비스를 실행하세요."
            )
    modes = next(
        (p["options"] for p in contract["parameters"] if p["key"] == "image_mode"), []
    )
    if images and not modes:
        errors.append(f"{d.label}: 이 모델은 참조 이미지를 사용하지 않습니다.")
    if d.providerInput.get("image_mode") == "first_last" and images < 2:
        errors.append(
            f"{d.label}: 첫·마지막 프레임 모드에는 참조 이미지 2개가 필요합니다."
        )
    return errors
