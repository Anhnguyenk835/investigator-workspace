"""Workers that take investigation runs off the queue."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from uuid import uuid4

from investigator.jobs.models import Job
from investigator.jobs.queue import JobQueue

log = logging.getLogger("investigator.worker")

Handler = Callable[[Job], Awaitable[None]]


def new_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:6]}"


class JobWorker:
    """Claims one job at a time and keeps its lease alive while it runs."""

    def __init__(
        self,
        queue: JobQueue,
        handler: Handler,
        *,
        worker_id: str | None = None,
        lease_s: float = 60.0,
        poll_s: float = 1.0,
    ) -> None:
        self.queue = queue
        self.handler = handler
        self.worker_id = worker_id or new_worker_id()
        self.lease_s = lease_s
        self.poll_s = poll_s

    async def run_once(self) -> bool:
        """Run the next job if there is one; True when a job was run."""
        job = await self.queue.claim(self.worker_id, self.lease_s)
        if job is None:
            return False
        beat = asyncio.create_task(self._keep_alive(job))
        try:
            await self.handler(job)
        except asyncio.CancelledError:
            # Shutting down: leave the lease to run out so another worker resumes the run.
            raise
        except Exception as exc:
            log.exception("job %s failed", job.id)
            await self.queue.fail(
                job.id, self.worker_id, f"{type(exc).__name__}: {exc}"
            )
        else:
            await self.queue.complete(job.id, self.worker_id)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
        return True

    async def _keep_alive(self, job: Job) -> None:
        while True:
            await asyncio.sleep(self.lease_s / 3)
            if not await self.queue.heartbeat(job.id, self.worker_id, self.lease_s):
                log.warning("lost the lease on job %s", job.id)
                return

    async def run_forever(self) -> None:
        while True:
            try:
                ran = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker loop error")
                ran = False
            if not ran:
                await asyncio.sleep(self.poll_s)
