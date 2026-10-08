import asyncio
import logging

from temporalio.worker import Worker

from .activities import Activities
from .config import get_settings
from .db import Database
from .temporal_client import connect
from .workflows import GenerationWorkflow


async def main():
    settings = get_settings()
    database = Database(settings)
    database.initialize()
    client = await connect(settings)
    activities = Activities(database, settings)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[GenerationWorkflow],
        activities=[
            activities.load_job,
            activities.cancelled,
            activities.execute_step,
            activities.poll_step,
            activities.cancel_step,
            activities.finish_job,
        ],
        max_concurrent_activities=4,
        max_concurrent_workflow_tasks=10,
    )
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
