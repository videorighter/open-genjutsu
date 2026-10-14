"""Shared model input contracts; vendor availability is separate from generation proof."""

import json
import logging
import threading
import time
from pathlib import Path

import httpx

from .security import allowed_remote

log = logging.getLogger("genjutsu")
CATALOG = json.loads(
    (Path(__file__).resolve().parents[2] / "models/catalog.json").read_text()
)
MAX_TOKENS = {
    "key": "max_tokens",
    "label": "최대 출력 토큰",
    "type": "integer",
    "minimum": 1,
    "maximum": 4096,
    "default": 1024,
}
ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
# ponytail: per-process memory cache; API refreshes it, submissions only read it.
_live = {"models": None, "fetched": 0.0, "attempted": 0.0}
_refreshing = threading.Lock()


def model_contract(provider, model):
    return next(
        (
            m
            for m in CATALOG["models"]
            if m["provider"] == provider and m["id"] == model
        ),
        None,
    )


def video_parameters(video, inputs):
    params = []

    def enum(key, label, options, default):
        if options:
            params.append(
                {
                    "key": key,
                    "label": label,
                    "type": "enum",
                    "options": options,
                    "default": default if default in options else options[0],
                }
            )

    enum("resolution", "해상도", video.get("supported_resolutions") or [], "720p")
    enum("duration", "길이(초)", sorted(video.get("supported_durations") or []), 5)
    enum(
        "aspect_ratio", "화면 비율", video.get("supported_aspect_ratios") or [], "16:9"
    )
    frames = video.get("supported_frame_images") or []
    modes = [
        mode
        for mode, ok in [
            ("first_frame", "first_frame" in frames),
            ("first_last", "last_frame" in frames),
            ("reference", "image" in inputs),
        ]
        if ok
    ]
    enum("image_mode", "참조 이미지 사용", modes, "first_frame")
    if modes:
        params[-1]["optionLabels"] = {
            "first_frame": "첫 프레임",
            "first_last": "첫·마지막 프레임",
            "reference": "인물·스타일 참조",
        }
    if video.get("generate_audio"):
        # Output keeps the source soundtrack, so generated audio is opt-in.
        params.append(
            {
                "key": "generate_audio",
                "label": "오디오 생성",
                "type": "boolean",
                "default": False,
            }
        )
    return params


def enum_parameter(key, label, options, default, labels=None):
    return {
        "key": key,
        "label": label,
        "type": "enum",
        "options": options,
        "default": default if default in options else options[0],
        **({"optionLabels": labels} if labels else {}),
    }


def normalize_openrouter(models, videos, images=()):
    videos = {v["id"]: v for v in videos}
    image_ids = {i["id"] for i in images}
    listed = {m["id"] for m in models}
    result = {}
    for m in models + [v for v in videos.values() if v["id"] not in listed]:
        arch = m.get("architecture") or {}
        inputs = arch.get("input_modalities") or []
        outputs = arch.get("output_modalities") or ["video"]
        contract = {
            "provider": "openrouter",
            "id": m["id"],
            "label": m.get("name") or m["id"],
            "inputs": inputs,
            "outputs": outputs,
            "kinds": [],
            "prompt": True,
            "vision": "image" in inputs,
            "generationVerified": False,
            "source": "https://openrouter.ai/api/v1/models",
            "pricing": m.get("pricing") or {},
            "parameters": [],
        }
        if m["id"] in videos:
            video = videos[m["id"]]
            contract.update(
                outputs=sorted({*outputs, "video"}),
                kinds=["motion", "edit"],
                seed=video.get("seed") is True,
                pricing=video.get("pricing_skus") or {},
                parameters=video_parameters(video, inputs),
            )
        elif "text" in outputs:
            sources = [
                mode
                for mode, ok in [
                    ("frames", "image" in inputs),
                    ("video", "video" in inputs),
                ]
                if ok
            ]
            params = [MAX_TOKENS]
            if "video" in inputs:
                params.append(
                    enum_parameter(
                        "analysis_input",
                        "분석 입력",
                        sources,
                        "frames",
                        {"frames": "샘플 프레임 3장", "video": "영상 전체"},
                    )  # fmt: skip
                )
            contract.update(
                kinds=["prompt", "analysis"] if sources else ["prompt"],
                parameters=params,
            )
        if m["id"] in image_ids:
            contract["kinds"] = [*contract["kinds"], "image"]
            contract["parameters"] = [
                *contract["parameters"],
                enum_parameter("aspect_ratio", "화면 비율", ASPECT_RATIOS, "1:1"),
            ]
        result[m["id"]] = contract
    return result


def fetch_openrouter(settings):
    base = settings.provider_base_urls["openrouter"].rstrip("/")
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:

        def get(path):
            response = client.get(allowed_remote(base + path, settings))
            response.raise_for_status()
            return response.json()["data"]

        return normalize_openrouter(
            get("/models?output_modalities=all"),
            get("/videos/models"),
            get("/images/models"),
        )


def openrouter_models(settings, refresh=False):
    """Live OpenRouter contracts by model ID, or None when never loaded."""
    now = time.time()
    if (
        refresh
        and not settings.testing
        and now - _live["fetched"] > settings.catalog_ttl_seconds
        and now - _live["attempted"] > 300
        and _refreshing.acquire(blocking=False)
    ):
        try:
            _live["attempted"] = now
            _live["models"] = fetch_openrouter(settings)
            _live["fetched"] = now
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("openrouter_catalog_refresh_failed type=%s", type(exc).__name__)
        finally:
            _refreshing.release()
    return _live["models"]


def openrouter_status():
    return {
        "available": _live["models"] is not None,
        "fetched": _live["fetched"] or None,
    }


def contract_for(data, live):
    if data.provider == "openrouter" and live is not None:
        return live.get(data.model)
    return model_contract(data.provider, data.model)


def pin_defaults(graph, live):
    """Snapshot OpenRouter video defaults so execution matches the validated estimate."""
    graph = json.loads(json.dumps(graph))
    for node in graph["nodes"]:
        data = node["data"]
        contract = (
            (live or {}).get(data["model"])
            if data["provider"] == "openrouter"
            else None
        )
        if contract and "video" in contract["outputs"]:
            defaults = {p["key"]: p["default"] for p in contract["parameters"]}
            data["providerInput"] = defaults | data.get("providerInput", {})
            if not contract.get("seed"):
                data["seed"] = ""  # Unsupported seeds make /videos answer 400.
    return graph


def estimate_usd(data, contract, images):
    """Pre-run estimate from per-second/per-image SKUs; None for other units."""
    if not contract or "video" not in contract.get("outputs", []):
        return None
    sku = contract["pricing"]
    values = {p["key"]: p.get("default") for p in contract["parameters"]}
    values.update(data.providerInput)
    seconds = values.get("duration")
    if type(seconds) is not int:
        return None
    res = str(values.get("resolution", "")).lower()
    cents = (
        sku.get(f"cents_per_video_output_second_{res}")
        or sku.get(f"cents_per_second_output_{res}")
        or sku.get("cents_per_second_output")
    )
    if cents:
        total = max(
            float(cents) * seconds,
            float(sku.get("minimum_cents_per_generation", 0)),
        )
        total += float(sku.get("cents_per_image_input", 0)) * images
        return round(total / 100, 4)
    # Dollar SKUs: most specific first (input kind, audio, resolution), then the base rate.
    audio = "with" if values.get("generate_audio") else "without"
    mode = "image" if images else "text"
    dollars = next(
        (
            sku[key]
            for key in [
                f"{mode}_to_video_duration_seconds_{res}",
                f"duration_seconds_{audio}_audio_{res}",
                f"duration_seconds_{audio}_audio",
                f"duration_seconds_{res}",
                "duration_seconds",
            ]
            if key in sku
        ),
        None,
    )
    if dollars is None:
        return None  # e.g. Seedance video_tokens: no public pixels-to-tokens rule.
    # MiniMax H3 billed $0.65 for 5s with one reference image: reference_images unused.
    return round(float(dollars) * seconds, 4)


def input_errors(data, contract=None):
    contract = contract or model_contract(data.provider, data.model)
    if not contract:
        return []
    errors = []
    if data.kind not in contract["kinds"]:
        errors.append(f"{data.label}: 이 모델은 {data.kind} 단계를 지원하지 않습니다.")
    for field in contract["parameters"]:
        key = field["key"]
        if key not in data.providerInput:
            continue
        value = data.providerInput[key]
        kind = field["type"]
        valid = True
        if kind == "boolean":
            valid = isinstance(value, bool)
        elif kind == "enum":
            # Type-strict so True cannot pass as duration 1.
            valid = any(value == o and type(value) is type(o) for o in field["options"])
        elif kind in {"integer", "number"}:
            valid = isinstance(
                value, int if kind == "integer" else (int, float)
            ) and not isinstance(value, bool)
            valid = valid and field["minimum"] <= value <= field["maximum"]
        if not valid:
            errors.append(
                f"{data.label}: {field['label']} 입력 형식 또는 범위를 확인하세요."
            )
    return errors
