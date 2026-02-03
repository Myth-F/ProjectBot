import logging

from fastapi import FastAPI

from .config import get_settings
from .logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="ProjectBot API", version="0.1.0")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    @app.get("/ready")
    async def ready() -> dict:
        return {"status": "ready"}

    return app


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    logging.getLogger("projectbot.api").info("Starting API on %s:%s", settings.api_host, settings.api_port)

    import uvicorn

    uvicorn.run("projectbot.api:create_app", host=settings.api_host, port=settings.api_port, factory=True)


if __name__ == "__main__":
    main()
