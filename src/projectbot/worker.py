import asyncio
import logging

from .config import get_settings
from .logging import configure_logging


async def run_worker(interval_seconds: int) -> None:
    logger = logging.getLogger("projectbot.worker")
    logger.info("Worker started with interval=%ss", interval_seconds)

    while True:
        logger.debug("Worker tick")
        await asyncio.sleep(interval_seconds)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    asyncio.run(run_worker(settings.worker_interval_seconds))


if __name__ == "__main__":
    main()
