"""In-memory queue used by tests and by ``make demo`` without Redis."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueuedJob:
    task_name: str
    payload: dict[str, object]
    job_id: str | None = None


@dataclass
class InMemoryTaskQueue:
    jobs: list[QueuedJob] = field(default_factory=list)
    available: bool = True

    async def enqueue(
        self, task_name: str, payload: dict[str, object], *, job_id: str | None = None
    ) -> str | None:
        if not self.available:
            raise RuntimeError("task queue is not available")
        self.jobs.append(QueuedJob(task_name=task_name, payload=payload, job_id=job_id))
        return job_id
