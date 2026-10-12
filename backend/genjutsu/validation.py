import re

from sqlalchemy import select

from .db import Asset, Credential
from .model_catalog import contract_for, estimate_usd, input_errors, openrouter_models
from .security import allowed_remote

ANIMATE = {"fal-ai/wan/v2.2-14b/animate/move", "fal-ai/wan/v2.2-14b/animate/replace"}
KLING = "fal-ai/kling-video/v3/pro/motion-control"
VACE = "fal-ai/wan-vace-14b"


def validate_execution(graph, session, user_id, settings, live=None):
    errors = []
    warnings = []
    paid = []
    if not graph.nodes or not any(n.data.kind == "output" for n in graph.nodes):
        errors.append("결과 내보내기 노드가 필요합니다.")
    if len(graph.nodes) > settings.max_nodes_per_job:
        errors.append(f"실행은 {settings.max_nodes_per_job}개 노드까지 지원합니다.")
    keys = {
        (key.provider, key.endpoint)
        for key in session.scalars(
            select(Credential).where(Credential.user_id == user_id)
        )
    }
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
            if d.provider != "local":
                errors.append(f"{d.label}: 입력 미디어는 Local을 사용하세요.")
            continue
        if not incoming[n.id]:
            errors.append(f"{d.label}: 입력 연결이 필요합니다.")
        if d.kind == "output":
            if d.provider != "local" or d.model != "ffmpeg":
                errors.append(f"{d.label}: 출력은 Local / ffmpeg를 사용하세요.")
            if not kinds(n) & {"video", "motion", "edit"}:
                errors.append(f"{d.label}: 영상 입력을 연결하세요.")
            continue
        paid.append(n)
        images = sum(x.data.kind in {"reference", "image"} for x in incoming[n.id])
        estimates.append(estimate_usd(d, contract, images))
        if (
            d.provider,
            (d.endpoint or "").rstrip("/") if d.provider in {"custom", "gpu"} else "",
        ) not in keys:
            errors.append(f"{d.label}: {d.provider} API 키를 등록하세요.")
        if d.kind in {"analysis", "prompt"}:
            tokens = d.providerInput.get("max_tokens", 1024)
            if (
                not isinstance(tokens, int)
                or isinstance(tokens, bool)
                or not 1 <= tokens <= 4096
            ):
                errors.append(f"{d.label}: max_tokens는 1~4096 정수여야 합니다.")
            if d.provider not in {"openrouter", "custom"}:
                errors.append(
                    f"{d.label}: 텍스트 단계는 OpenRouter 또는 OpenAI 호환 Custom API를 사용하세요."
                )
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
            if d.provider != "openrouter":
                errors.append(f"{d.label}: 이미지 생성은 OpenRouter를 사용하세요.")
            if not d.prompt.strip() and not kinds(n) & {"prompt", "analysis"}:
                errors.append(f"{d.label}: 만들 이미지를 설명하는 지시를 입력하세요.")
        elif d.provider == "fal":
            if (
                d.model == KLING
                and d.providerInput.get("character_orientation", "video") == "image"
            ):
                for source in incoming[n.id]:
                    asset = (
                        session.get(Asset, source.data.assetId)
                        if source.data.assetId
                        else None
                    )
                    if (
                        asset
                        and source.data.kind == "video"
                        and asset.metadata_json.get("duration", 0) > 10
                    ):
                        errors.append(
                            f"{d.label}: image 방향 기준은 10초 이하 원본 영상을 사용하세요."
                        )
            if settings.media_delivery == "upload":
                warnings.append(
                    f"{d.label}: 입력 미디어를 fal 저장소에 업로드해 모델에 전달합니다."
                )
            elif not settings.testing and not settings.public_url.startswith(
                "https://"
            ):
                errors.append(
                    "외부 영상 API 사용에는 공급자가 접근할 수 있는 HTTPS 서비스 주소가 필요합니다."
                )
            if d.model not in ANIMATE | {KLING, VACE}:
                errors.append(f"{d.label}: 현재 지원하는 fal 모델을 선택하세요.")
            if not kinds(n) & {"video", "motion", "edit"}:
                errors.append(f"{d.label}: 영상 입력이 필요합니다.")
            if d.model in ANIMATE | {KLING} and not kinds(n) & {"reference", "image"}:
                errors.append(f"{d.label}: 참조 이미지 입력이 필요합니다.")
            if d.model in ANIMATE:
                if d.resolution == "1080p":
                    errors.append(
                        f"{d.label}: Wan-Animate는 480p/580p/720p를 사용하세요."
                    )
                if d.prompt.strip() or "prompt" in kinds(n):
                    warnings.append(
                        f"{d.label}: Wan-Animate는 프롬프트를 받지 않으며 움직임·참조 이미지로 생성합니다."
                    )
            if d.model == VACE and d.providerInput.get("task", "pose") not in {
                "pose",
                "depth",
                "inpainting",
                "outpainting",
                "reframe",
            }:
                errors.append(f"{d.label}: 올바른 VACE task가 필요합니다.")
            if (
                d.model == VACE
                and d.providerInput.get("task") == "inpainting"
                and not (
                    d.providerInput.get("mask_video_url")
                    or d.providerInput.get("mask_image_url")
                )
            ):
                errors.append(f"{d.label}: inpainting 마스크 입력을 지정하세요.")
        elif d.provider == "replicate":
            if settings.media_delivery == "upload":
                warnings.append(
                    f"{d.label}: 입력 미디어를 Replicate 파일 API에 업로드해 모델에 전달합니다."
                )
            elif not settings.testing and not settings.public_url.startswith(
                "https://"
            ):
                errors.append(
                    "외부 영상 API 사용에는 공급자가 접근할 수 있는 HTTPS 서비스 주소가 필요합니다."
                )
            if not re.fullmatch(r"[\w-]+/[\w.-]+", d.model):
                errors.append(
                    f"{d.label}: Replicate 모델은 owner/name 형식이어야 합니다."
                )
            if not d.providerInput:
                errors.append(
                    f"{d.label}: 모델에 맞는 Replicate 입력 JSON을 지정하세요."
                )
        elif d.provider == "openrouter":
            errors.extend(
                openrouter_video_errors(d, contract, kinds(n), images, settings)
            )
        elif d.provider not in {"custom", "gpu"}:
            errors.append(f"{d.label}: 영상 단계에 사용할 수 없는 공급자입니다.")
        if d.provider in {"custom", "gpu"}:
            try:
                allowed_remote(d.endpoint or "", settings, custom=True)
            except ValueError:
                errors.append(f"{d.label}: 운영자가 허용한 API 주소를 입력하세요.")
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
                f"{d.label}: 이 모델은 입력 영상을 반영하지 않습니다. 영상 입력을 지원하는 모델을 선택하세요."
            )
        elif not settings.testing and not settings.public_url.startswith("https://"):
            # OpenRouter accepts only HTTPS video references (data URLs are rejected).
            errors.append(
                f"{d.label}: OpenRouter 영상 참조에는 공급자가 접근할 수 있는 HTTPS 서비스 주소가 필요합니다. 로컬에서는 fal 또는 Replicate를 사용하세요."
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
