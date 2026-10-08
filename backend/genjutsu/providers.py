import base64
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from .db import Asset, Credential, Step
from .media import asset_path, sampled_frames, store_asset
from .security import allowed_remote, cipher, sign_asset
from .validation import ANIMATE, KLING, VACE


class Rejected(Exception):
    pass


class Ambiguous(Exception):
    pass


def signed_url(settings, asset_id):
    expires = int(time.time()) + min(settings.job_timeout_seconds + 3600, 86000)
    return f"{settings.public_url.rstrip('/')}/api/assets/{asset_id}/content?expires={expires}&token={sign_asset(settings.secret_key, asset_id, expires)}"


def recovered_ticket(data, request_id, settings):
    provider = data["provider"]
    if provider == "fal":
        # Queue API uses the model owner/model prefix for subsequent requests.
        model = "/".join(data["model"].split("/")[:2])
        base = f"{settings.provider_base_urls['fal'].rstrip('/')}/{model}/requests/{request_id}"
        return {
            "status_url": base + "/status",
            "result_url": base,
            "cancel_url": base + "/cancel",
        }
    base = f"{settings.provider_base_urls['replicate'].rstrip('/')}/predictions/{request_id}"
    return {"status_url": base, "result_url": base, "cancel_url": base + "/cancel"}


def inputs_for(session, job, node):
    refs = [e["source"] for e in job.graph["edges"] if e["target"] == node["id"]]
    values = [
        session.scalar(
            select(Step).where(Step.job_id == job.id, Step.node_id == id)
        ).output
        or {}
        for id in refs
    ]
    images = []
    videos = []
    texts = []
    for value in values:
        if value.get("text"):
            texts.append(value["text"])
        if value.get("asset_id"):
            asset = session.get(Asset, value["asset_id"])
            if not asset or asset.user_id != job.user_id:
                raise Rejected("입력 자산을 찾을 수 없습니다.")
            (videos if asset.mime.startswith("video/") else images).append(asset)
    return images, videos, texts


def credential(session, user_id, provider, settings, endpoint=""):
    c = session.scalar(
        select(Credential).where(
            Credential.user_id == user_id,
            Credential.provider == provider,
            Credential.endpoint
            == (endpoint.rstrip("/") if provider in {"custom", "gpu"} else ""),
        )
    )
    if not c:
        raise Rejected("공급자 API 키가 없습니다.")
    return cipher(settings.secret_key).decrypt(c.encrypted_key.encode()).decode()


def replace_values(value, refs):
    if isinstance(value, str):
        return refs.get(value, value)
    if isinstance(value, list):
        return [replace_values(x, refs) for x in value]
    if isinstance(value, dict):
        return {k: replace_values(v, refs) for k, v in value.items()}
    return value


async def submit_provider(session, job, node, settings):
    import asyncio

    d = node["data"]
    provider = d["provider"]
    key = credential(
        session, job.user_id, provider, settings, node["data"].get("endpoint", "")
    )
    images, videos, texts = inputs_for(session, job, node)
    video = signed_url(settings, videos[0].id) if videos else None
    image = signed_url(settings, images[0].id) if images else None
    prompt = "\n\n".join([d.get("prompt", "")] + texts)
    extra = replace_values(
        d.get("providerInput", {}),
        {
            "$video": video,
            "$image": image,
            "$prompt": prompt,
            "$images": [signed_url(settings, a.id) for a in images],
        },
    )
    headers = {"Authorization": ("Key " if provider == "fal" else "Bearer ") + key}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60, connect=10), follow_redirects=False, trust_env=False
    ) as client:
        if d["kind"] in {"analysis", "prompt"}:
            base = (
                settings.provider_base_urls["openrouter"]
                if provider == "openrouter"
                else d["endpoint"]
            )
            allowed_remote(base, settings, custom=provider == "custom")
            content = [{"type": "text", "text": prompt}]
            if d["kind"] == "analysis":
                try:
                    frames = await asyncio.to_thread(
                        sampled_frames, settings, videos[0]
                    )
                except Exception:
                    raise Rejected(
                        "입력 영상의 분석 프레임을 만들지 못했습니다."
                    ) from None
                for frame in frames:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64,"
                                + base64.b64encode(frame).decode()
                            },
                        }
                    )
            payload = {
                "model": d["model"],
                "messages": [{"role": "user", "content": content}],
                "temperature": d["temperature"],
                "max_tokens": min(int(extra.get("max_tokens", 1024)), 4096),
                "stream": False,
            }
            response = await client.post(
                base.rstrip("/") + "/chat/completions", headers=headers, json=payload
            )
            check_submission(response)
            try:
                text = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise Ambiguous("모델 응답을 확인해야 합니다.") from exc
            if not isinstance(text, str) or len(text) > 50000:
                raise Ambiguous("모델 응답을 확인해야 합니다.")
            return {"text": text}, None, None
        if provider == "fal":
            url = settings.provider_base_urls["fal"].rstrip("/") + "/" + d["model"]
            allowed_remote(url, settings)
            payload = dict(extra)
            if d["model"] in ANIMATE:
                payload.update(
                    {
                        "video_url": video,
                        "image_url": image,
                        "resolution": d["resolution"],
                    }
                )
            elif d["model"] == KLING:
                if prompt.strip():
                    payload["prompt"] = prompt
                payload.update(
                    {
                        "video_url": video,
                        "image_url": image,
                        "character_orientation": extra.get(
                            "character_orientation", "video"
                        ),
                        "keep_original_sound": extra.get("keep_original_sound", True),
                    }
                )
            elif d["model"] == VACE:
                payload.update(
                    {
                        "video_url": video,
                        "prompt": prompt,
                        "task": extra.get("task", "pose"),
                        "ref_image_urls": [signed_url(settings, a.id) for a in images],
                    }
                )
            if d.get("seed"):
                payload["seed"] = int(d["seed"])
            response = await client.post(url, headers=headers, json=payload)
            check_submission(response)
            data = response.json()
            id = data.get("request_id")
            if not isinstance(id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", id):
                raise Ambiguous("공급자 접수 ID를 확인해야 합니다.")
            ticket = recovered_ticket(d, id, settings)
            for source, target in [
                ("status_url", "status_url"),
                ("response_url", "result_url"),
                ("cancel_url", "cancel_url"),
            ]:
                if data.get(source):
                    candidate = allowed_remote(data[source], settings)
                    expected = urlsplit(settings.provider_base_urls["fal"])
                    actual = urlsplit(candidate)
                    if (actual.hostname, actual.port) != (
                        expected.hostname,
                        expected.port,
                    ):
                        raise Ambiguous("공급자 조회 주소를 확인해야 합니다.")
                    ticket[target] = candidate
            return None, id, ticket
        if provider == "replicate":
            base = settings.provider_base_urls["replicate"].rstrip("/")
            url = base + "/models/" + d["model"] + "/predictions"
            allowed_remote(url, settings)
            response = await client.post(url, headers=headers, json={"input": extra})
            check_submission(response)
            data = response.json()
            id = data.get("id")
            if not isinstance(id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", id):
                raise Ambiguous("공급자 접수 ID를 확인해야 합니다.")
            return None, id, recovered_ticket(d, id, settings)
        base = d["endpoint"].rstrip("/")
        allowed_remote(base, settings, custom=True)
        response = await client.post(
            base + "/jobs",
            headers=headers,
            json={
                "model": d["model"],
                "task": d["kind"],
                "prompt": prompt,
                "parameters": {
                    "temperature": d["temperature"],
                    "seed": d.get("seed"),
                    "resolution": d["resolution"],
                    **extra,
                },
                "video_url": video,
                "image_url": image,
            },
        )
        check_submission(response)
        data = response.json()
        id = data.get("request_id")
        if not isinstance(id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", id):
            raise Ambiguous("공급자 접수 ID를 확인해야 합니다.")
        ticket = {
            "status_url": base + "/jobs/" + id,
            "result_url": base + "/jobs/" + id,
            "cancel_url": base + "/jobs/" + id + "/cancel",
        }
        return None, id, ticket


def check_submission(response):
    if response.status_code in {400, 401, 403, 404, 405, 413, 422, 429}:
        raise Rejected("공급자가 요청을 거절했습니다. API 키와 모델 입력을 확인하세요.")
    if response.status_code >= 300:
        raise Ambiguous("공급자 접수 여부를 운영자가 확인해야 합니다.")


async def poll_provider(session, job, node, step, settings):
    provider = node["data"]["provider"]
    key = credential(
        session, job.user_id, provider, settings, node["data"].get("endpoint", "")
    )
    headers = {"Authorization": ("Key " if provider == "fal" else "Bearer ") + key}
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.get(
            allowed_remote(step.ticket["status_url"], settings), headers=headers
        )
        response.raise_for_status()
        data = response.json()
        state = str(data.get("status", "")).upper()
        if state in {"FAILED", "ERROR"}:
            return {"state": "FAILED"}
        if state in {"CANCELLED", "CANCELED"}:
            return {"state": "CANCELLED"}
        if state not in {"COMPLETED", "SUCCEEDED"}:
            return {"state": "PENDING"}
        if provider == "fal":
            response = await client.get(
                allowed_remote(step.ticket["result_url"], settings), headers=headers
            )
            response.raise_for_status()
            data = response.json()
            url = (
                data.get("video", {}).get("url")
                if isinstance(data.get("video"), dict)
                else None
            )
        elif provider == "replicate":
            output = data.get("output")
            url = (
                output
                if isinstance(output, str)
                else next((v for v in output or [] if isinstance(v, str)), None)
            )
        else:
            url = data.get("video_url") or data.get("output_url")
        if not url:
            raise ValueError("Provider did not return a video URL")
        return {
            "state": "COMPLETE",
            "url": allowed_remote(url, settings, download=True),
        }


async def cancel_provider(session, job, node, step, settings):
    provider = node["data"]["provider"]
    key = credential(
        session, job.user_id, provider, settings, node["data"].get("endpoint", "")
    )
    async with httpx.AsyncClient(
        timeout=15, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.post(
            allowed_remote(step.ticket["cancel_url"], settings),
            headers={
                "Authorization": ("Key " if provider == "fal" else "Bearer ") + key
            },
        )
        return response.status_code < 300


async def download_video(settings, user_id, url):
    import asyncio

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result"
            size = 0
            # CDN redirects are revalidated individually; credentials are never forwarded.
            for redirect in range(4):
                allowed_remote(url, settings, download=True)
                async with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        from urllib.parse import urljoin

                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    with path.open("wb") as out:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > settings.max_upload_mb * 1024 * 1024:
                                raise ValueError("Result exceeds media size limit")
                            out.write(chunk)
                    asset = await asyncio.to_thread(
                        store_asset, settings, user_id, "generated.mp4", path
                    )
                    if not asset.mime.startswith("video/"):
                        asset_path(settings, asset.id).unlink(missing_ok=True)
                        raise ValueError("Provider result is not a video")
                    return asset
            raise ValueError("Too many result redirects")
