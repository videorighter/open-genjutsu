import asyncio
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
    cancel_provider,
    download_video,
    inputs_for,
    poll_provider,
    submit_provider,
)
from .schemas import Graph

log = logging.getLogger("genjutsu.worker")


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
                    "공급자 접수 여부 확인이 필요합니다.",
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
                step.output = {"asset_id": asset.id}
                step.status = "COMPLETE"
                db.commit()
                return {"state": "COMPLETE"}
            if kind == "output":
                images, videos, texts = inputs_for(db, job, node)
                if not videos:
                    raise ApplicationError(
                        "출력할 영상이 없습니다.", non_retryable=True
                    )
                source_id = next(
                    (
                        n["data"].get("assetId")
                        for n in job.graph["nodes"]
                        if n["data"]["kind"] == "video"
                    ),
                    None,
                )
                source = db.get(Asset, source_id) if source_id else None
                asset = await asyncio.to_thread(
                    self.encode_output, job.user_id, videos[0], source
                )
                try:
                    self.commit_asset(db, job.user_id, asset)
                except Exception:
                    asset_path(self.settings, asset.id).unlink(missing_ok=True)
                    raise
                step.output = {"asset_id": asset.id}
                step.status = "COMPLETE"
                db.commit()
                return {"state": "COMPLETE"}
            # Persist a submission intent before touching a paid provider. Never automatically repeat it.
            step.status = "STARTING"
            db.commit()
            try:
                output, request_id, ticket = await submit_provider(
                    db, job, node, self.settings
                )
                step.output = output
                step.provider_id = request_id
                step.ticket = ticket
                step.status = "COMPLETE" if output else "SUBMITTED"
                db.commit()
                return {"state": "COMPLETE" if output else "PENDING"}
            except Rejected:
                step.status = "FAILED"
                step.error = (
                    "공급자가 요청을 거절했습니다. 모델 입력 또는 API 키를 확인하세요."
                )
                db.commit()
                raise ApplicationError(
                    step.error, type="ProviderRejected", non_retryable=True
                )
            except Exception as exc:
                db.rollback()
                step = db.scalar(
                    select(Step).where(Step.job_id == job_id, Step.node_id == node_id)
                )
                step.status = "UNKNOWN"
                step.error = "공급자 접수 여부를 운영자가 확인해야 합니다."
                db.commit()
                log.warning(
                    "submission_unknown job=%s node=%s type=%s",
                    job_id,
                    node_id,
                    type(exc).__name__,
                )
                raise ApplicationError(
                    step.error, type="SubmissionUnknown", non_retryable=True
                ) from None

    def commit_asset(self, db, user_id, asset):
        from .db import User

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

    def encode_output(self, user_id, video, source):
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
            if source and source.id != video.id:
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
            command += [
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
                "-t",
                str(video.metadata_json["duration"]),
                "-movflags",
                "+faststart",
                str(target),
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            return store_asset(self.settings, user_id, "genjutsu-result.mp4", target)

    @activity.defn
    async def poll_step(self, args: list[str]) -> dict:
        job_id, node_id = args
        with self.database.session() as db:
            job, step, node = self.get(db, job_id, node_id)
            if step.status == "COMPLETE":
                return {"state": "COMPLETE"}
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
            if result["state"] == "COMPLETE":
                try:
                    asset = await download_video(
                        self.settings, job.user_id, result["url"]
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
                try:
                    self.commit_asset(db, job.user_id, asset)
                except Exception:
                    asset_path(self.settings, asset.id).unlink(missing_ok=True)
                    raise
                step.output = {"asset_id": asset.id}
                step.status = "COMPLETE"
                db.commit()
            elif result["state"] in {"FAILED", "CANCELLED"}:
                step.status = result["state"]
                step.error = (
                    "공급자 작업이 실패했습니다."
                    if result["state"] == "FAILED"
                    else None
                )
                db.commit()
            return {"state": result["state"]}

    @activity.defn
    async def cancel_step(self, args: list[str]) -> bool:
        with self.database.session() as db:
            job, step, node = self.get(db, *args)
            if not step.ticket or step.status != "SUBMITTED":
                return False
            try:
                return await cancel_provider(db, job, node, step, self.settings)
            except Exception:
                return False

    @activity.defn
    async def finish_job(self, args: list[str]) -> str:
        job_id, state, message = args
        with self.database.session.begin() as db:
            j = db.get(Job, job_id)
            steps = list(db.scalars(select(Step).where(Step.job_id == job_id)))
            if any(s.status in {"UNKNOWN", "STARTING"} for s in steps):
                state = "NEEDS_REVIEW"
                message = "공급자 접수 여부를 운영자가 확인해야 합니다."
            elif state == "FAILED" and any(s.status == "SUBMITTED" for s in steps):
                state = "NEEDS_REVIEW"
                message = "접수된 공급자 작업을 운영자가 확인해야 합니다."
            j.status = state
            j.error = message or None
            j.updated = now()
            return state
