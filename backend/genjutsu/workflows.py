from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn(name="GenerationWorkflowV1")
class GenerationWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> str:
        safe = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=5),
        )

        async def call(name, arg, seconds=30, retry=safe):
            return await workflow.execute_activity(
                name,
                arg,
                start_to_close_timeout=timedelta(seconds=seconds),
                retry_policy=retry,
            )

        state = "FAILED"
        message = "작업이 실패했습니다."
        try:
            plan = await call("load_job", job_id)
            deadline = workflow.now() + timedelta(seconds=plan["timeout"])
            for item in plan["nodes"]:
                id = item["id"] if isinstance(item, dict) else item
                local = isinstance(item, dict) and item.get("local", False)
                if await call("cancelled", job_id):
                    state = "CANCELLED"
                    message = ""
                    break
                result = await call(
                    "execute_step",
                    [job_id, id],
                    180,
                    safe if local else RetryPolicy(maximum_attempts=1),
                )
                cancellation_sent = False
                while result["state"] == "PENDING":
                    if workflow.now() >= deadline:
                        raise RuntimeError("deadline")
                    if not cancellation_sent and await call("cancelled", job_id):
                        await call(
                            "cancel_step",
                            [job_id, id],
                            20,
                            RetryPolicy(maximum_attempts=1),
                        )
                        cancellation_sent = True
                    await workflow.sleep(timedelta(seconds=5))
                    result = await call("poll_step", [job_id, id], 180)
                if result["state"] == "FAILED":
                    break
                if result["state"] == "CANCELLED":
                    state = "CANCELLED"
                    message = ""
                    break
            else:
                state = "CANCELLED" if await call("cancelled", job_id) else "SUCCEEDED"
                message = ""
        except (ActivityError, RuntimeError):
            pass
        # This activity is idempotent and projects the terminal state for the UI.
        return await call("finish_job", [job_id, state, message])
