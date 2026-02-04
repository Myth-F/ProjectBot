import asyncio
import logging
import uuid

from .config import get_settings
from .db import init_db
from .logging import configure_logging, log_context


async def run_worker(interval_seconds: int) -> None:
    logger = logging.getLogger("projectbot.worker")
    logger.info("Worker started with interval=%ss", interval_seconds)

    while True:
        with log_context(correlation_id=uuid.uuid4().hex):
            logger.debug("Worker tick")
        await asyncio.sleep(interval_seconds)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    async def _main() -> None:
        await init_db()
        await run_worker(settings.worker_interval_seconds)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
