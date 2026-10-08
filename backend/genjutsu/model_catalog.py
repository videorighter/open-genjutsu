"""Shared model input contracts; vendor availability is separate from generation proof."""

import json
from pathlib import Path
from urllib.parse import urlsplit

CATALOG = json.loads(
    (Path(__file__).resolve().parents[2] / "models/catalog.json").read_text()
)


def model_contract(provider, model):
    return next(
        (
            m
            for m in CATALOG["models"]
            if m["provider"] == provider and m["id"] == model
        ),
        None,
    )


def input_errors(data):
    contract = model_contract(data.provider, data.model)
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
            valid = value in field["options"]
        elif kind in {"integer", "number"}:
            valid = isinstance(
                value, int if kind == "integer" else (int, float)
            ) and not isinstance(value, bool)
            valid = valid and field["minimum"] <= value <= field["maximum"]
        elif kind == "url":
            valid = isinstance(value, str)
            if valid and value not in {"$image", "$video"}:
                try:
                    parsed = urlsplit(value)
                    valid = (
                        parsed.scheme == "https"
                        and bool(parsed.hostname)
                        and not parsed.username
                        and not parsed.password
                    )
                except ValueError:
                    valid = False
        if not valid:
            errors.append(
                f"{data.label}: {field['label']} 입력 형식 또는 범위를 확인하세요."
            )
    return errors
