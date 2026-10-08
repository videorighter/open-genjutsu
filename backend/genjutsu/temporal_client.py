import asyncio
import dataclasses
import logging
from datetime import timedelta

from sqlalchemy import select
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.converter import DataConverter
from temporalio.exceptions import WorkflowAlreadyStartedError

from .db import Job, now
from .security import EncryptedPayloadCodec

log = logging.getLogger("genjutsu.dispatcher")


async def connect(settings):
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls,
        api_key=settings.temporal_api_key or None,
        data_converter=dataclasses.replace(
            DataConverter.default,
            payload_codec=EncryptedPayloadCodec(settings.secret_key),
        ),
    )


def workflow_id(job):
    return f"generation-{job.id}-v{job.run_revision}"


async def dispatch_loop(app):
    settings = app.state.settings
    database = app.state.database
    client = None
    while True:
        try:
            if client is None:
                client = await connect(settings)
            await client.service_client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=settings.temporal_namespace)
            )
            app.state.temporal_ready = True
            with database.session() as db:
                pending = list(
                    db.scalars(
                        select(Job)
                        .where(Job.dispatched.is_(False), Job.status == "QUEUED")
                        .limit(100)
                    )
                )
            for job in pending:
                try:
                    await client.start_workflow(
                        "GenerationWorkflowV1",
                        job.id,
                        id=workflow_id(job),
                        task_queue=settings.temporal_task_queue,
                        execution_timeout=timedelta(
                            seconds=settings.job_timeout_seconds + 600
                        ),
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    )
                except WorkflowAlreadyStartedError:
                    pass
                with database.session.begin() as db:
                    j = db.get(Job, job.id)
                    if j and j.run_revision == job.run_revision:
                        j.dispatched = True
                        j.updated = now()
            # Closed workflows without a final DB projection require operator review, never resubmission.
            with database.session() as db:
                stale = list(
                    db.scalars(
                        select(Job)
                        .where(
                            Job.status == "RUNNING",
                            Job.updated
                            < now()
                            - timedelta(seconds=settings.job_timeout_seconds + 600),
                        )
                        .limit(20)
                    )
                )
            for job in stale:
                description = await client.get_workflow_handle(
                    workflow_id(job)
                ).describe()
                if description.status.name not in {"RUNNING"}:
                    with database.session.begin() as db:
                        j = db.get(Job, job.id)
                        if j.status == "RUNNING":
                            j.status = "NEEDS_REVIEW"
                            j.error = "작업 실행 이력을 운영자가 확인해야 합니다."
                            j.updated = now()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            app.state.temporal_ready = False
            client = None
            log.warning("dispatch_unavailable type=%s", type(exc).__name__)
        await asyncio.sleep(2)
