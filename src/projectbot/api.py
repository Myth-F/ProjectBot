import logging
import uuid

from fastapi import FastAPI, Request

from .config import get_settings
from .db import init_db
from .logging import configure_logging, log_context


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="ProjectBot API", version="0.1.0")

    @app.on_event("startup")
    async def startup() -> None:
        await init_db()

    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        correlation_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        with log_context(correlation_id=correlation_id):
            response = await call_next(request)
        response.headers["X-Request-Id"] = correlation_id
        return response

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
