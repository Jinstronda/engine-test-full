"""Scheduler — runs async functions on cron schedules using APScheduler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from app.config import AsyncFunctionConfig, EngineConfig, ScheduleConfig

logger = logging.getLogger(__name__)


def build_trigger(schedule: ScheduleConfig) -> CronTrigger:
    """Convert a ScheduleConfig into an APScheduler CronTrigger."""
    match schedule.frequency:
        case "daily":
            return CronTrigger(hour=schedule.hour)
        case "weekly":
            return CronTrigger(day_of_week=schedule.day_of_week, hour=schedule.hour)
        case "monthly":
            return CronTrigger(day=schedule.day_of_month, hour=schedule.hour)
        case _:
            raise ValueError(f"Unknown schedule frequency: {schedule.frequency}")


async def run_async_function(fn: AsyncFunctionConfig, config: EngineConfig) -> None:
    """Execute an async function by running its system with the configured prompt."""
    from app.runtime import execute_run

    logger.info(f"Running async function for system '{fn.system_id}'")

    try:
        system = config.get_system(fn.system_id)
    except ValueError as e:
        logger.error(f"Async function error: {e}")
        return

    try:
        final_output = None
        async for chunk in execute_run(config, system, fn.prompt):
            if chunk.type == "token":
                final_output = chunk.content
            elif chunk.type == "error":
                logger.error(f"Async function '{fn.system_id}' error: {chunk.content}")

        if final_output:
            logger.info(
                f"Async function '{fn.system_id}' completed. "
                f"Output: {final_output[:200]}{'...' if len(final_output) > 200 else ''}"
            )
    except Exception as e:
        logger.error(f"Async function '{fn.system_id}' failed: {e}", exc_info=True)


def setup_scheduler(config: EngineConfig) -> AsyncIOScheduler:
    """Build and configure the scheduler from the engine config."""
    scheduler = AsyncIOScheduler()

    for fn in config.async_functions:
        trigger = build_trigger(fn.schedule)
        scheduler.add_job(
            run_async_function,
            trigger=trigger,
            args=[fn, config],
            id=f"async_{fn.system_id}",
            replace_existing=True,
        )
        logger.info(
            f"Scheduled async function: system={fn.system_id}, "
            f"frequency={fn.schedule.frequency}, hour={fn.schedule.hour}"
        )

    return scheduler
