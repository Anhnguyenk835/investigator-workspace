"""A standalone worker: `python -m investigator.worker`.

Takes investigation runs off the Postgres queue. Run as many as needed; set
EMBEDDED_WORKERS=0 on the API so only these do the work."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from investigator.jobs import JobWorker
from investigator.jobs.handler import RunHandler
from investigator.runtime import open_runtime
from investigator.settings import get_settings

log = logging.getLogger("investigator.worker")


async def main(concurrency: int = 2) -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    async with open_runtime(settings) as rt:
        if rt.graph is None:
            raise SystemExit("LLM gateway is not configured. Set LITELLM_API_KEY.")
        handler = RunHandler(rt.graph, rt.store, rt.access, rt.events, rt.directory)
        workers = [
            JobWorker(rt.queue, handler, lease_s=settings.job_lease_seconds)
            for _ in range(concurrency)
        ]
        tasks = [asyncio.create_task(w.run_forever()) for w in workers]
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        log.info("worker started with %d slot(s)", concurrency)
        await stop.wait()
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t


if __name__ == "__main__":
    asyncio.run(main())
