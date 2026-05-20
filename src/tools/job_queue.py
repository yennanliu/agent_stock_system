"""
In-memory async job queue for the analysis pipeline.

Each job gets a UUID. Events are published to a per-job asyncio.Queue and
also stored in an event history list so late/re-connecting SSE clients can
replay missed events.

The pipeline task keeps running even if the SSE client disconnects — the
client can reconnect via /api/jobs/{job_id}/stream and get the full history
plus any new events.

Max concurrent jobs: MAX_CONCURRENT (default 10).
Job TTL: jobs are pruned after JOB_TTL_SECONDS (default 30 min).
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator

log = logging.getLogger(__name__)

MAX_CONCURRENT = 10
JOB_TTL_SECONDS = 1800   # 30 min


@dataclass
class _Job:
    job_id: str
    ticker: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"          # pending | running | done | error
    events: list[dict] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


_jobs: dict[str, _Job] = {}
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


# ── Job lifecycle ─────────────────────────────────────────────────────────────

def create_job(ticker: str) -> str:
    _prune_old_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = _Job(job_id=job_id, ticker=ticker)
    return job_id


def get_job(job_id: str) -> _Job | None:
    return _jobs.get(job_id)


def job_status(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    return {
        "job_id":     job.job_id,
        "ticker":     job.ticker,
        "status":     job.status,
        "created_at": job.created_at,
        "event_count": len(job.events),
    }


def _prune_old_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    stale  = [jid for jid, j in _jobs.items() if j.created_at < cutoff and j.status in ("done", "error")]
    for jid in stale:
        del _jobs[jid]


# ── Publisher (called from pipeline coroutine) ────────────────────────────────

async def publish(job_id: str, event: dict) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job.events.append(event)
    await job.queue.put(event)

    stage = (event.get("data") or "{}")
    # update job status based on stage field in SSE data
    try:
        import json
        d = json.loads(stage)
        if d.get("stage") == "complete" or d.get("stage") == "critique_complete":
            job.status = "done"
        elif d.get("stage") == "error":
            job.status = "error"
    except Exception:
        pass


# ── Consumer (SSE stream) ─────────────────────────────────────────────────────

async def stream_job(job_id: str) -> AsyncGenerator[dict, None]:
    """Yield all events for a job: first replay history, then live."""
    job = _jobs.get(job_id)
    if job is None:
        yield {"data": '{"stage":"error","message":"Job not found"}'}
        return

    # Replay already-seen events
    replayed = len(job.events)
    for ev in job.events:
        yield ev

    # If job is already finished, we're done
    if job.status in ("done", "error"):
        return

    # Stream new live events
    while True:
        try:
            event = await asyncio.wait_for(job.queue.get(), timeout=60)
            yield event
            try:
                import json
                d = json.loads(event.get("data", "{}"))
                if d.get("stage") in ("complete", "critique_complete", "error"):
                    return
            except Exception:
                pass
        except asyncio.TimeoutError:
            if job.status in ("done", "error"):
                return
            yield {"data": '{"stage":"ping","message":"…"}'}


# ── Start a pipeline job in the background ────────────────────────────────────

def start_pipeline_job(job_id: str, coro_factory) -> None:
    """Schedule the pipeline coroutine as a background asyncio task."""
    job = _jobs.get(job_id)
    if job is None:
        return
    job.status = "running"

    async def _run():
        sem = _get_semaphore()
        async with sem:
            try:
                async for event in coro_factory():
                    await publish(job_id, event)
            except Exception as e:
                log.exception("Job %s pipeline error: %s", job_id, e)
                await publish(job_id, {"data": f'{{"stage":"error","message":"{e}"}}'})
        job.status = "done"

    job.task = asyncio.create_task(_run())
