"""
ProjectBot Worker
=================
Background worker for scheduled tasks and maintenance jobs.
"""

import asyncio
import logging
import time
import uuid

from .config import get_settings
from .db import init_db, ping_db
from .logging import configure_logging, log_context, metrics
from .redis_client import ping_redis


LOGGER = logging.getLogger("projectbot.worker")


async def health_check() -> dict[str, bool]:
    """Check health of all dependencies."""
    db_ok = await ping_db()
    redis_ok = await ping_redis()
    return {"database": db_ok, "redis": redis_ok}


async def run_worker(interval_seconds: int) -> None:
    """
    Main worker loop.

    Executes periodic tasks at the configured interval.
    Currently includes:
    - Health monitoring
    - Future: Task reminders, cleanup jobs, etc.
    """
    tick_count = 0

    LOGGER.info(
        "Worker started interval=%ds",
        interval_seconds,
    )

    while True:
        tick_count += 1
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()

        with log_context(
            correlation_id=correlation_id,
            operation="worker.tick",
        ):
            try:
                # Periodic health check (every 12 ticks = ~1 minute with 5s interval)
                if tick_count % 12 == 0:
                    health = await health_check()
                    duration_ms = (time.perf_counter() - start_time) * 1000

                    all_ok = all(health.values())
                    metrics.record("worker.health_check", duration_ms, success=all_ok)

                    LOGGER.info(
                        "Health check db=%s redis=%s duration=%.2fms",
                        health["database"],
                        health["redis"],
                        duration_ms,
                    )

                # Log worker activity at DEBUG level
                LOGGER.debug("Worker tick #%d", tick_count)

            except Exception as e:
                LOGGER.exception("Worker tick failed: %s", e)
                metrics.record("worker.tick", 0, success=False)

        await asyncio.sleep(interval_seconds)


async def _async_main() -> None:
    """Async entry point."""
    settings = get_settings()

    LOGGER.info("Initializing worker database connection")
    await init_db()

    LOGGER.info("Database initialized, starting worker loop")
    await run_worker(settings.worker_interval_seconds)


def main() -> None:
    """Main entry point for the worker service."""
    settings = get_settings()
    json_format = settings.environment == "prod"
    configure_logging(settings.log_level, json_format=json_format)

    LOGGER.info(
        "Starting worker env=%s interval=%ds format=%s",
        settings.environment,
        settings.worker_interval_seconds,
        "json" if json_format else "text",
    )

    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        LOGGER.info("Worker stopped by user")
    except Exception as e:
        LOGGER.critical("Worker crashed: %s", e)
        raise


if __name__ == "__main__":
    main()
