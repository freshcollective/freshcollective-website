"""FIP3 — background reconciler for finite-plan grace expiry.

Sweeps ``purchase_plans`` where ``status='payment_problem'`` and
``grace_expires_at <= now`` and suspends them via
:func:`services.finite_plan_lifecycle.sweep_expired_grace_plans`.

The loop uses the same asyncio + FastAPI-lifespan pattern as
``services/scheduled_publisher.py``. The scheduler is
in-process — there is no external queue in this project — but the
work it does (a WHERE + row-lock + status change) is trivially
safe to run from any process. If a future deploy adds a proper job
runner, replace :func:`start_reconciler` with a call from the new
scheduler; the sweep function remains the entry point either way.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.services.finite_plan_lifecycle import sweep_expired_grace_plans


logger = logging.getLogger(__name__)


# 5 minutes. Grace resolution matters at hour granularity (7-day
# window), so a 5-minute tick is more than fast enough while
# keeping DB load negligible.
_TICK_SECONDS = 300


def sweep_once() -> int:
    """Session-managing wrapper — returns the count of plans suspended."""
    db = SessionLocal()
    try:
        outcomes = sweep_expired_grace_plans(db, now=datetime.utcnow())
        return len(outcomes)
    finally:
        db.close()


_task: asyncio.Task | None = None


async def _loop() -> None:
    logger.info("finite_plan_reconciler loop starting (tick=%ss)", _TICK_SECONDS)
    while True:
        try:
            count = await asyncio.to_thread(sweep_once)
            if count:
                logger.info("finite_plan_reconciler: suspended %d plan(s)", count)
        except Exception:
            logger.exception("finite_plan_reconciler iteration failed")
        await asyncio.sleep(_TICK_SECONDS)


def start_reconciler() -> None:
    """Fire-and-forget task launcher used from the app lifespan."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="finite_plan_reconciler")


async def stop_reconciler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
