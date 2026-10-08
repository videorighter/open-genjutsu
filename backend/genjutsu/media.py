import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .db import Asset, new_id

Image.MAX_IMAGE_PIXELS = 16_000_000


def asset_path(settings, asset_id):
    return settings.data_dir / "assets" / asset_id


def inspect_media(path: Path, settings):
    with path.open("rb") as f:
        magic = f.read(32)
    if magic.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (
        magic.startswith(b"RIFF") and magic[8:12] == b"WEBP"
    ):
        try:
            with Image.open(path) as image:
                image.load()
                if image.width * image.height > 16_000_000:
                    raise ValueError("Image exceeds 16 megapixels")
                mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[
                    image.format
                ]
                return mime, {"width": image.width, "height": image.height}
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            KeyError,
            OSError,
        ) as exc:
            raise ValueError("Invalid image file") from exc
    if not (magic[4:8] == b"ftyp" or magic.startswith(b"\x1a\x45\xdf\xa3")):
        raise ValueError("Only JPEG, PNG, WebP, MP4 and WebM media are supported")
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        data = json.loads(result.stdout)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        duration = float(data["format"].get("duration", video.get("duration", 0)))
        if not 0 < duration <= settings.max_video_seconds:
            raise ValueError(
                f"Video must be between 0 and {settings.max_video_seconds} seconds"
            )
        if video.get("width", 0) * video.get("height", 0) > 3840 * 2160:
            raise ValueError("Video exceeds 4K dimensions")
        return ("video/mp4" if magic[4:8] == b"ftyp" else "video/webm"), {
            "duration": duration,
            "width": video["width"],
            "height": video["height"],
            "audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        }
    except (
        subprocess.SubprocessError,
        StopIteration,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Invalid or unreadable video") from exc


def store_asset(settings, user_id, filename, source: Path):
    mime, metadata = inspect_media(source, settings)
    size = source.stat().st_size
    if size > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("Media is too large")
    with source.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    asset = Asset(
        id=new_id(),
        user_id=user_id,
        filename=Path(filename).name[:300] or "media",
        mime=mime,
        size=size,
        checksum=checksum,
        metadata_json=metadata,
    )
    folder = settings.data_dir / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (asset.id + ".partial")
    shutil.copyfile(source, temporary)
    os.replace(temporary, folder / asset.id)
    return asset


def sampled_frames(settings, asset, count=3):
    duration = asset.metadata_json.get("duration", 1)
    with tempfile.TemporaryDirectory() as temp:
        result = []
        for i in range(count):
            target = Path(temp) / f"{i}.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-ss",
                    str(duration * (i + 1) / (count + 1)),
                    "-i",
                    str(asset_path(settings, asset.id)),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=512:-2",
                    "-threads",
                    "1",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            result.append(target.read_bytes())
        return result
