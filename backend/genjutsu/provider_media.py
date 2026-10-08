"""Upload owned inputs using official provider file APIs before model submission.

Contracts: fal-client's GCS storage upload and replicate-python's files.create.
No generation POST is issued here; URLs and credentials stay out of error messages.
"""

import asyncio
import json
import mimetypes
from urllib.parse import urlsplit

import httpx

from .media import asset_path
from .security import allowed_remote


class MediaUploadFailed(Exception):
    pass


async def chunks(file):
    while data := await asyncio.to_thread(file.read, 1024 * 1024):
        yield data


async def upload_inputs(client, assets, provider, key, settings):
    try:
        # Leave time for the generation POST within the existing 180s activity.
        async with asyncio.timeout(90):
            return await _upload_inputs(client, assets, provider, key, settings)
    except TimeoutError:
        raise MediaUploadFailed(
            "Input upload deadline exceeded before generation submission"
        ) from None


async def _upload_inputs(client, assets, provider, key, settings):
    urls = {}
    try:
        for asset in assets:
            if asset.id in urls:
                continue
            path = asset_path(settings, asset.id)
            if (
                path.stat().st_size != asset.size
                or asset.size > settings.max_upload_mb * 1024 * 1024
            ):
                raise ValueError("Input file size is invalid")
            filename = asset.id + (mimetypes.guess_extension(asset.mime) or ".bin")
            if provider == "fal":
                base = settings.provider_base_urls["fal_storage"].rstrip("/")
                initiate = base + "/storage/upload/initiate?storage_type=gcs"
                allowed_remote(initiate, settings)
                response = await client.post(
                    initiate,
                    json={"file_name": filename, "content_type": asset.mime},
                    headers={
                        "Authorization": "Key " + key,
                        "X-Fal-Object-Lifecycle-Preference": json.dumps(
                            {
                                "expiration_duration_seconds": min(
                                    settings.job_timeout_seconds + 3600, 86400
                                )
                            }
                        ),
                    },
                )
                response.raise_for_status()
                data = response.json()
                upload_url, file_url = data["upload_url"], data["file_url"]
                allowed_remote(upload_url, settings, upload=True)
                allowed_remote(file_url, settings, download=True)
                with path.open("rb") as file:
                    response = await client.put(
                        upload_url,
                        content=chunks(file),
                        headers={
                            "Content-Type": asset.mime,
                            "Content-Length": str(asset.size),
                        },
                        timeout=httpx.Timeout(300, connect=10),
                    )
                response.raise_for_status()
            elif provider == "replicate":
                base = settings.provider_base_urls["replicate"].rstrip("/")
                endpoint = base + "/files"
                allowed_remote(endpoint, settings)
                with path.open("rb") as file:
                    response = await client.post(
                        endpoint,
                        files={"content": (filename, file, asset.mime)},
                        headers={"Authorization": "Bearer " + key},
                        timeout=httpx.Timeout(300, connect=10),
                    )
                response.raise_for_status()
                file_url = response.json()["urls"]["get"]
                allowed_remote(file_url, settings)
                if urlsplit(file_url).netloc != urlsplit(base).netloc or not urlsplit(
                    file_url
                ).path.startswith(urlsplit(base).path + "/files/"):
                    raise ValueError("Unexpected provider file URL")
            else:
                raise ValueError("Unsupported upload provider")
            urls[asset.id] = file_url
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
        raise MediaUploadFailed(
            "Provider input upload failed before generation submission"
        ) from None
    return urls
