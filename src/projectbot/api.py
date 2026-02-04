"""
ProjectBot API
==============
FastAPI service with health endpoints and observability.
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request, Response

from .config import get_settings
from .db import init_db, ping_db
from .logging import configure_logging, log_context, metrics
from .redis_client import ping_redis


LOGGER = logging.getLogger("projectbot.api")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    json_format = settings.environment == "prod"
    configure_logging(settings.log_level, json_format=json_format)

    app = FastAPI(
        title="ProjectBot API",
        version="0.1.0",
        description="REST API for ProjectBot",
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url=None,
    )

    # ========================================================================
    # Lifecycle Events
    # ========================================================================

    @app.on_event("startup")
    async def startup() -> None:
        LOGGER.info("Starting API service env=%s", settings.environment)
        await init_db()
        LOGGER.info("Database initialized")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        LOGGER.info("Shutting down API service")

    # ========================================================================
    # Middleware
    # ========================================================================

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next) -> Response:
        """Add request context, correlation ID, and timing to all requests."""
        correlation_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        start_time = time.perf_counter()

        with log_context(
            correlation_id=correlation_id,
            operation=f"http.{request.method.lower()}.{request.url.path}",
        ):
            LOGGER.info(
                "Request started method=%s path=%s",
                request.method,
                request.url.path,
            )

            response = await call_next(request)

            duration_ms = (time.perf_counter() - start_time) * 1000
            metrics.record(
                f"http.{request.method.lower()}",
                duration_ms,
                success=response.status_code < 400,
            )

            LOGGER.info(
                "Request completed status=%d duration=%.2fms",
                response.status_code,
                duration_ms,
            )

        response.headers["X-Request-Id"] = correlation_id
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        return response

    # ========================================================================
    # Health Endpoints
    # ========================================================================

    @app.get("/health")
    async def health() -> dict:
        """Basic health check - returns immediately."""
        return {
            "status": "ok",
            "environment": settings.environment,
            "service": "projectbot-api",
        }

    @app.get("/ready")
    async def ready() -> dict:
        """
        Readiness check - verifies all dependencies are available.
        Used by orchestrators to determine if the service can receive traffic.
        """
        start_time = time.perf_counter()

        db_ok = await ping_db()
        redis_ok = await ping_redis()

        duration_ms = (time.perf_counter() - start_time) * 1000
        all_ok = db_ok and redis_ok

        LOGGER.info(
            "Readiness check db=%s redis=%s duration=%.2fms",
            db_ok,
            redis_ok,
            duration_ms,
        )

        return {
            "status": "ready" if all_ok else "degraded",
            "checks": {
                "database": "ok" if db_ok else "error",
                "redis": "ok" if redis_ok else "error",
            },
            "duration_ms": round(duration_ms, 2),
        }

    @app.get("/metrics")
    async def metrics_endpoint() -> dict:
        """Return internal metrics for monitoring."""
        all_stats = metrics.get_all_stats()

        return {
            "operations": all_stats,
            "total_operations": sum(s["count"] for s in all_stats) if all_stats else 0,
        }

    return app


def main() -> None:
    """Main entry point for the API service."""
    settings = get_settings()
    json_format = settings.environment == "prod"
    configure_logging(settings.log_level, json_format=json_format)

    LOGGER.info(
        "Starting API on %s:%s env=%s format=%s",
        settings.api_host,
        settings.api_port,
        settings.environment,
        "json" if json_format else "text",
    )

    import uvicorn

    uvicorn.run(
        "projectbot.api:create_app",
        host=settings.api_host,
        port=settings.api_port,
        factory=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
