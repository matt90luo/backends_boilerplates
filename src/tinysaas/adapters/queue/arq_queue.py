"""arq (Redis) task queue adapter."""

from __future__ import annotations

from tinysaas.infrastructure.resources import Resources


class ArqTaskQueue:
    """Enqueues jobs onto the Redis pool created by the resource manager."""

    def __init__(self, resources: Resources) -> None:
        self._resources = resources

    async def enqueue(
        self, task_name: str, payload: dict[str, object], *, job_id: str | None = None
    ) -> str | None:
        pool = self._resources.arq_pool
        if pool is None:
            raise RuntimeError("task queue is not available")
        job = await pool.enqueue_job(task_name, payload, _job_id=job_id)
        if job is None:
            # arq reports None when a job with this id already exists, which is
            # exactly what we want for an idempotent submission.
            return job_id
        return job.job_id
