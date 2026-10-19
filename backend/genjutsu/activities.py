import asyncio
import base64
import logging
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .db import Asset, Job, Step, now
from .media import asset_path, store_asset
from .providers import (
    Rejected,
    download_video,
    inputs_for,
    output_audio,
    poll_provider,
    submit_provider,
    upstream_source,
)
from .schemas import Graph

log = logging.getLogger("genjutsu.worker")
# H.264/AAC MP4 that browsers and providers accept.
MP4 = [
    "-c:v",
    "libx264",
    "-preset",
    "fast",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
    "-threads",
    "2",
    "-c:a",
    "aac",
    "-movflags",
    "+faststart",
]


class Activities:
    def __init__(self, database, settings):
        self.database = database
        self.settings = settings

    def get(self, session, job_id, node_id):
        job = session.get(Job, job_id)
        if not job:
            raise ApplicationError("작업이 없습니다.", non_retryable=True)
        step = session.scalar(
            select(Step).where(Step.job_id == job_id, Step.node_id == node_id)
        )
        node = next(n for n in job.graph["nodes"] if n["id"] == node_id)
        return job, step, node

    @activity.defn
    async def load_job(self, job_id: str) -> dict:
        with self.database.session.begin() as db:
            job = db.get(Job, job_id)
            graph = Graph.model_validate(job.graph)
            if job.status == "QUEUED":
                job.status = "RUNNING"
                job.updated = now()
            return {
                "nodes": [
                    {
                        "id": n.id,
                        "local": n.data.kind in {"video", "reference", "output"},
                    }
                    for n in graph.ordered()
                ],
                "timeout": self.settings.job_timeout_seconds,
            }

    @activity.defn
    async def cancelled(self, job_id: str) -> bool:
        with self.database.session() as db:
            return db.get(Job, job_id).cancel_requested

    @activity.defn
    async def execute_step(self, args: list[str]) -> dict:
        job_id, node_id = args
        with self.database.session() as db:
            job, step, node = self.get(db, job_id, node_id)
            if step.status == "COMPLETE":
                return {"state": "COMPLETE"}
            if job.cancel_requested and step.status == "PENDING":
                return {"state": "CANCELLED"}
            if step.status == "SUBMITTED":
                return {"state": "PENDING"}
            if step.status in {"STARTING", "UNKNOWN"}:
                step.status = "UNKNOWN"
                db.commit()
                raise ApplicationError(
                    "공급자가 생성 요청을 받았는지 확인해야 합니다.",
                    type="SubmissionUnknown",
                    non_retryable=True,
                )
            if step.status == "FAILED":
                raise ApplicationError("이전 단계가 실패했습니다.", non_retryable=True)
            kind = node["data"]["kind"]
            if kind in {"video", "reference"}:
                asset = db.get(Asset, node["data"].get("assetId"))
                if (
                    not asset
                    or asset.user_id != job.user_id
                    or not asset_path(self.settings, asset.id).is_file()
                ):
                    raise ApplicationError(
                        "입력 미디어를 찾을 수 없습니다.", non_retryable=True
                    )
                if kind == "video" and (clip := node["data"].get("range")):
                    # Every later step reads this step's media, so they all see only the 구간.
                    start, end = clip["start"], clip["end"]
                    name = f"{Path(asset.filename).stem}_{start:.1f}-{end:.1f}s.mp4"
                    asset = await asyncio.to_thread(
                        self.cut, job.user_id, asset, start, end - start, name
                    )
                    self.commit_asset(db, job.user_id, asset)
                step.output = {"asset_id": asset.id}
                step.status = "COMPLETE"
                db.commit()
                return {"state": "COMPLETE"}
            if kind == "output":
                images, videos, texts = inputs_for(db, job, node)
                if not videos and not images:
                    raise ApplicationError(
                        "내보낼 이미지나 영상이 없습니다.", non_retryable=True
                    )
                if not videos:
                    # Images are already stored media; the result is the image itself.
                    step.output = {"asset_id": images[0].id}
                    step.status = "COMPLETE"
                    db.commit()
                    return {"state": "COMPLETE"}
                audio = output_audio(job.graph, node)
                source = None
                if audio == "source":
                    # The 원본 영상 step's media is its 구간, so the audio follows the range.
                    done = db.scalar(
                        select(Step.output).where(
                            Step.job_id == job_id,
                            Step.node_id == upstream_source(job.graph, node["id"]),
                        )
                    )
                    source = db.get(Asset, done["asset_id"]) if done else None
                    if not source or source.user_id != job.user_id:
                        raise ApplicationError(
                            "원본 오디오를 가져올 원본 영상이 없습니다.",
                            non_retryable=True,
                        )
                asset = await asyncio.to_thread(
                    self.encode_output, job.user_id, videos[0], source, audio
                )
                self.commit_asset(db, job.user_id, asset)
                step.output = {"asset_id": asset.id}
                step.status = "COMPLETE"
                db.commit()
                return {"state": "COMPLETE"}
            if chunks := node["data"].get("chunks"):
                # 나눠 생성: this request is 조각 1; poll_step submits the rest in turn.
                clip = await self.chunk_clip(db, job, node, 0, chunks)
                progress = {"chunk": 0, "chunks": chunks, "clips": [clip.id]}
                return await self.submit(
                    db, job, step, node, progress | {"parts": [], "cost": 0}, [clip]
                )
            return await self.submit(db, job, step, node)

    async def submit(self, db, job, step, node, progress=None, videos=None, frame=None):
        """Submit one paid request. The intent is persisted first and never repeated."""
        step.status = "STARTING"
        step.ticket = progress or step.ticket
        db.commit()
        try:
            output, request_id, ticket = await submit_provider(
                db, job, node, self.settings, videos, frame
            )
            if asset := (output or {}).pop("_asset", None):
                self.commit_asset(db, job.user_id, asset)
            step.output = output
            step.provider_id = request_id
            # The new request's status/result URLs replace the previous 조각's.
            step.ticket = ticket and {**(progress or {}), **ticket}
            step.status = "COMPLETE" if output else "SUBMITTED"
            db.commit()
            return {"state": "COMPLETE" if output else "PENDING"}
        except Rejected as exc:
            step.status = "FAILED"
            # Fixed Korean text plus provider_reason, which strips URLs and keys.
            step.error = (
                str(exc)
                or "공급자가 요청을 거절했습니다. 모델 옵션 또는 API 키를 확인하세요."
            )
            await self.keep_partial(db, job, step)
            db.commit()
            raise ApplicationError(
                step.error, type="ProviderRejected", non_retryable=True
            )
        except Exception as exc:
            db.rollback()
            step = db.get(Step, step.id)
            step.status = "UNKNOWN"
            step.error = "공급자가 생성 요청을 받았는지 운영자가 확인해야 합니다."
            db.commit()
            log.warning(
                "submission_unknown job=%s node=%s type=%s",
                job.id,
                step.node_id,
                type(exc).__name__,
            )
            raise ApplicationError(
                step.error, type="SubmissionUnknown", non_retryable=True
            ) from None

    async def chunk_clip(self, db, job, node, index, chunks):
        """조각 `index` of the step's input video, stored so the provider can fetch it."""
        _, videos, _ = inputs_for(db, job, node)
        seconds = videos[0].metadata_json["duration"] / chunks
        name = f"조각 원본 {index + 1}-{chunks}.mp4"
        clip = await asyncio.to_thread(
            self.cut, job.user_id, videos[0], index * seconds, seconds, name
        )
        self.commit_asset(db, job.user_id, clip)
        return clip

    async def keep_partial(self, db, job, step):
        """A stopped 나눠 생성 joins its finished 조각 into a 부분 영상 and drops the rest."""
        ticket = step.ticket or {}
        if not ticket.get("chunks"):
            return
        if ticket["parts"]:
            try:
                parts = [db.get(Asset, id) for id in ticket["parts"]]
                partial = await asyncio.to_thread(
                    self.stitch, job.user_id, parts, "부분 영상.mp4"
                )
                self.commit_asset(db, job.user_id, partial)
                step.output = {
                    "partial_asset_id": partial.id,
                    "cost_usd": ticket["cost"],
                }
            except Exception as exc:
                log.warning(
                    "partial_video_failed job=%s type=%s", job.id, type(exc).__name__
                )
        self.discard(db, [*ticket["clips"], *ticket["parts"]])

    def discard(self, db, ids):
        """Delete working media (조각 inputs and results), committing the step with it."""
        for id in ids:
            if asset := db.get(Asset, id):
                db.delete(asset)
        db.commit()
        for id in ids:
            asset_path(self.settings, id).unlink(missing_ok=True)

    def commit_asset(self, db, user_id, asset):
        """Add a stored file under the storage quota, or delete the file."""
        from .db import User

        try:
            db.scalar(select(User).where(User.id == user_id).with_for_update())
            used = db.scalar(
                select(func.coalesce(func.sum(Asset.size), 0)).where(
                    Asset.user_id == user_id
                )
            )
            if used + asset.size > self.settings.user_storage_mb * 1024 * 1024:
                raise ValueError("Media storage quota exceeded")
            db.add(asset)
            db.flush()
        except Exception:
            asset_path(self.settings, asset.id).unlink(missing_ok=True)
            raise

    def cut(self, user_id, video, start, seconds, filename):
        """Re-encode `seconds` from `start` so the cut lands on the exact frame."""
        # ponytail: one 2-thread encode inside the 180s activity; long 4K 구간 can
        # time out, move to a dedicated activity with a longer timeout if that happens.
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "cut.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-ss",
                    str(start),
                    "-i",
                    str(asset_path(self.settings, video.id)),
                    "-t",
                    str(seconds),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    *MP4,
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=150,
            )
            return store_asset(self.settings, user_id, filename, target)

    def stitch(self, user_id, parts, filename):
        """Join 조각 that cut() encoded alike, without re-encoding."""
        with tempfile.TemporaryDirectory() as folder:
            listing = Path(folder) / "parts.txt"
            listing.write_text(
                "".join(f"file '{asset_path(self.settings, p.id)}'\n" for p in parts)
            )
            target = Path(folder) / "joined.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(listing),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=150,
            )
            return store_asset(self.settings, user_id, filename, target)

    def last_frame(self, video):
        """The final frame as a JPEG data URL: the 약한 연결 to the next 조각 (ADR 0001)."""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "last.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-sseof",
                    "-0.5",
                    "-i",
                    str(asset_path(self.settings, video.id)),
                    "-update",
                    "1",
                    "-q:v",
                    "3",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            return (
                "data:image/jpeg;base64,"
                + base64.b64encode(target.read_bytes()).decode()
            )

    def encode_output(self, user_id, video, source, audio="source"):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result.mp4"
            command = [
                "ffmpeg",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(asset_path(self.settings, video.id)),
            ]
            if audio == "none":
                command += ["-map", "0:v:0", "-an"]
            elif source and source.id != video.id:
                command += [
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(asset_path(self.settings, source.id)),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a?",
                ]
            else:
                command += ["-map", "0:v:0", "-map", "0:a?"]
            command += [*MP4, "-t", str(video.metadata_json["duration"]), str(target)]
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            return store_asset(self.settings, user_id, "genjutsu-result.mp4", target)

    @activity.defn
    async def poll_step(self, args: list[str]) -> dict:
        job_id, node_id = args
        with self.database.session() as db:
            job, step, node = self.get(db, job_id, node_id)
            if step.status == "COMPLETE":
                return {"state": "COMPLETE"}
            if step.status in {"STARTING", "UNKNOWN"}:
                # A 조각 submission was interrupted: never repeat a paid request.
                step.status = "UNKNOWN"
                step.error = "공급자가 생성 요청을 받았는지 운영자가 확인해야 합니다."
                db.commit()
                raise ApplicationError(
                    step.error, type="SubmissionUnknown", non_retryable=True
                )
            ticket = step.ticket or {}
            chunks = ticket.get("chunks")
            # A 나눠 생성 step may already hold the current 조각 (retry after saving it).
            if not chunks or len(ticket["parts"]) == ticket["chunk"]:
                try:
                    result = await poll_provider(db, job, node, step, self.settings)
                except Exception as exc:
                    log.warning(
                        "provider_poll_delayed job=%s node=%s type=%s",
                        job_id,
                        node_id,
                        type(exc).__name__,
                    )
                    raise ApplicationError(
                        "공급자 상태 조회가 지연됐습니다.", type="ProviderUnavailable"
                    ) from None
                if result["state"] in {"FAILED", "CANCELLED"}:
                    step.status = result["state"]
                    reason = result.get("reason")
                    step.error = (
                        "생성 요청이 실패했습니다."
                        + (f" 사유: {reason}" if reason else "")
                        + (f" (조각 {ticket['chunk'] + 1}/{chunks})" if chunks else "")
                        if result["state"] == "FAILED"
                        else None
                    )
                    await self.keep_partial(db, job, step)
                    db.commit()
                    return {"state": result["state"]}
                if result["state"] != "COMPLETE":
                    return {"state": result["state"]}
                try:
                    asset = await download_video(
                        self.settings,
                        job.user_id,
                        result["url"],
                        result.get("headers"),
                    )
                except Exception as exc:
                    log.warning(
                        "result_download_delayed job=%s type=%s",
                        job_id,
                        type(exc).__name__,
                    )
                    raise ApplicationError(
                        "결과 다운로드가 지연됐습니다.", type="ResultUnavailable"
                    ) from None
                if chunks:
                    clip = db.get(Asset, ticket["clips"][ticket["chunk"]])
                    target, name = (
                        clip.metadata_json["duration"],
                        f"조각 {ticket['chunk'] + 1}-{chunks}.mp4",
                    )
                else:
                    _, videos, _ = inputs_for(db, job, node)
                    target = videos[0].metadata_json["duration"] if videos else None
                    name = "generated.mp4"
                # The model made the shortest allowed duration; keep the 구간 length.
                # 조각 are always re-encoded alike so they join without re-encoding.
                if chunks or (
                    target and asset.metadata_json["duration"] > target + 0.05
                ):
                    generated = asset
                    try:
                        asset = await asyncio.to_thread(
                            self.cut, job.user_id, generated, 0, target, name
                        )
                    finally:
                        asset_path(self.settings, generated.id).unlink(missing_ok=True)
                self.commit_asset(db, job.user_id, asset)
                if not chunks:
                    step.output = {
                        "asset_id": asset.id,
                        **(
                            {"cost_usd": result["cost_usd"]}
                            if "cost_usd" in result
                            else {}
                        ),
                    }
                    step.status = "COMPLETE"
                    db.commit()
                    return {"state": "COMPLETE"}
                step.ticket = ticket = {
                    **ticket,
                    "parts": [*ticket["parts"], asset.id],
                    "cost": ticket["cost"] + result.get("cost_usd", 0),
                }
                db.commit()
            # The current 조각 is saved: join them all, stop on cancel, or submit the next.
            if len(ticket["parts"]) == chunks:
                parts = [db.get(Asset, id) for id in ticket["parts"]]
                joined = await asyncio.to_thread(
                    self.stitch, job.user_id, parts, "generated.mp4"
                )
                self.commit_asset(db, job.user_id, joined)
                step.output = {"asset_id": joined.id, "cost_usd": ticket["cost"]}
                step.status = "COMPLETE"
                self.discard(db, [*ticket["clips"], *ticket["parts"]])
                return {"state": "COMPLETE"}
            if job.cancel_requested:
                step.status = "CANCELLED"
                await self.keep_partial(db, job, step)
                db.commit()
                return {"state": "CANCELLED"}
            index = len(ticket["parts"])
            frame = None
            if node["data"].get("providerInput", {}).get("image_mode") == "reference":
                previous = db.get(Asset, ticket["parts"][-1])
                frame = await asyncio.to_thread(self.last_frame, previous)
            clip = await self.chunk_clip(db, job, node, index, chunks)
            progress = {**ticket, "chunk": index, "clips": [*ticket["clips"], clip.id]}
            return await self.submit(db, job, step, node, progress, [clip], frame)

    @activity.defn
    async def cancel_step(self, args: list[str]) -> bool:
        # Kept for workflow history: OpenRouter has no cancel API, so the
        # workflow keeps polling an accepted step to its final state.
        return False

    @activity.defn
    async def finish_job(self, args: list[str]) -> str:
        job_id, state, message = args
        with self.database.session.begin() as db:
            j = db.get(Job, job_id)
            steps = list(db.scalars(select(Step).where(Step.job_id == job_id)))
            if any(s.status in {"UNKNOWN", "STARTING"} for s in steps):
                state = "NEEDS_REVIEW"
                message = "공급자가 생성 요청을 받았는지 운영자가 확인해야 합니다."
            elif state == "FAILED" and any(s.status == "SUBMITTED" for s in steps):
                state = "NEEDS_REVIEW"
                message = "공급자가 받은 생성 요청을 운영자가 확인해야 합니다."
            j.status = state
            j.error = message or None
            j.updated = now()
            return state
