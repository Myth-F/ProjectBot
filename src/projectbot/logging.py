"""
ProjectBot Logging Module
=========================
Structured logging with context propagation and observability features.
"""

from __future__ import annotations

import functools
import json
import logging
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, TypeVar

# ============================================================================
# Context Variables
# ============================================================================

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
workspace_id_var: ContextVar[str] = ContextVar("workspace_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")
guild_id_var: ContextVar[str] = ContextVar("guild_id", default="-")
channel_id_var: ContextVar[str] = ContextVar("channel_id", default="-")
operation_var: ContextVar[str] = ContextVar("operation", default="-")

_base_factory = logging.getLogRecordFactory()
_factory_set = False


# ============================================================================
# Log Record Factory
# ============================================================================

def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Custom log record factory that injects context variables."""
    record = _base_factory(*args, **kwargs)
    record.correlation_id = correlation_id_var.get()
    record.workspace_id = workspace_id_var.get()
    record.user_id = user_id_var.get()
    record.guild_id = guild_id_var.get()
    record.channel_id = channel_id_var.get()
    record.operation = operation_var.get()
    return record


# ============================================================================
# Formatters
# ============================================================================

class StructuredFormatter(logging.Formatter):
    """
    Structured log formatter for human-readable console output.

    Format:
    2024-01-15 10:30:45 | INFO  | projectbot.bot | [cmd:task.add] Message
                       | cid=abc123 gid=456 uid=789
    """

    LEVEL_COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True) -> None:
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        # Timestamp
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Level with optional color
        level = record.levelname
        if self.use_colors:
            color = self.LEVEL_COLORS.get(level, "")
            level_str = f"{color}{level:5}{self.RESET}"
        else:
            level_str = f"{level:5}"

        # Logger name (shortened)
        name = record.name
        if name.startswith("projectbot."):
            name = name[11:]  # Remove prefix

        # Operation tag
        operation = getattr(record, "operation", "-")
        op_tag = f"[{operation}]" if operation != "-" else ""

        # Main line
        main_line = f"{ts_str} | {level_str} | {name:12} | {op_tag} {record.getMessage()}"

        # Context line (only if we have meaningful context)
        cid = getattr(record, "correlation_id", "-")
        gid = getattr(record, "guild_id", "-")
        uid = getattr(record, "user_id", "-")

        context_parts = []
        if cid != "-":
            context_parts.append(f"cid={cid[:12]}")
        if gid != "-":
            context_parts.append(f"gid={gid}")
        if uid != "-":
            context_parts.append(f"uid={uid}")

        if context_parts:
            indent = " " * 22  # Align with main line
            context_line = f"{indent}| {' '.join(context_parts)}"
            return f"{main_line}\n{context_line}"

        return main_line


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for production/log aggregation systems.

    Output:
    {"ts":"2024-01-15T10:30:45Z","level":"INFO","logger":"projectbot.bot",...}
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)

        log_entry = {
            "ts": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
            "workspace_id": getattr(record, "workspace_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "guild_id": getattr(record, "guild_id", "-"),
            "channel_id": getattr(record, "channel_id", "-"),
            "operation": getattr(record, "operation", "-"),
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Clean up empty values
        log_entry = {k: v for k, v in log_entry.items() if v and v != "-"}

        return json.dumps(log_entry, ensure_ascii=False)


# ============================================================================
# Configuration
# ============================================================================

def configure_logging(level: str, json_format: bool = False) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON output format (for production)
    """
    global _factory_set
    if not _factory_set:
        logging.setLogRecordFactory(_record_factory)
        _factory_set = True

    # Clear existing handlers
    root = logging.getLogger()
    root.handlers.clear()

    # Create handler with appropriate formatter
    handler = logging.StreamHandler(sys.stdout)

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(StructuredFormatter())

    # Configure root logger
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Reduce noise from third-party libraries
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


# ============================================================================
# Context Manager
# ============================================================================

@contextmanager
def log_context(
    *,
    correlation_id: str | None = None,
    workspace_id: str | None = None,
    user_id: str | None = None,
    guild_id: str | None = None,
    channel_id: str | None = None,
    operation: str | None = None,
) -> Iterator[None]:
    """
    Context manager for setting log context variables.

    Usage:
        with log_context(correlation_id="abc123", operation="task.create"):
            logger.info("Creating task")
            # All logs within this block will have the context attached
    """
    tokens: dict[ContextVar[str], Any] = {}

    if correlation_id is not None:
        tokens[correlation_id_var] = correlation_id_var.set(correlation_id)
    if workspace_id is not None:
        tokens[workspace_id_var] = workspace_id_var.set(workspace_id)
    if user_id is not None:
        tokens[user_id_var] = user_id_var.set(user_id)
    if guild_id is not None:
        tokens[guild_id_var] = guild_id_var.set(guild_id)
    if channel_id is not None:
        tokens[channel_id_var] = channel_id_var.set(channel_id)
    if operation is not None:
        tokens[operation_var] = operation_var.set(operation)

    try:
        yield
    finally:
        for var, token in tokens.items():
            var.reset(token)


# ============================================================================
# Observability Helpers
# ============================================================================

T = TypeVar("T", bound=Callable[..., Any])


class OperationMetrics:
    """Simple metrics collector for operations."""

    def __init__(self) -> None:
        self._operations: dict[str, dict[str, Any]] = {}

    def record(
        self,
        operation: str,
        duration_ms: float,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an operation execution."""
        if operation not in self._operations:
            self._operations[operation] = {
                "count": 0,
                "success_count": 0,
                "error_count": 0,
                "total_duration_ms": 0.0,
                "min_duration_ms": float("inf"),
                "max_duration_ms": 0.0,
            }

        stats = self._operations[operation]
        stats["count"] += 1
        if success:
            stats["success_count"] += 1
        else:
            stats["error_count"] += 1
        stats["total_duration_ms"] += duration_ms
        stats["min_duration_ms"] = min(stats["min_duration_ms"], duration_ms)
        stats["max_duration_ms"] = max(stats["max_duration_ms"], duration_ms)

    def get_stats(self, operation: str) -> dict[str, Any] | None:
        """Get stats for a specific operation."""
        stats = self._operations.get(operation)
        if not stats:
            return None

        avg_duration = stats["total_duration_ms"] / stats["count"] if stats["count"] > 0 else 0

        return {
            "operation": operation,
            "count": stats["count"],
            "success_rate": stats["success_count"] / stats["count"] if stats["count"] > 0 else 0,
            "avg_duration_ms": round(avg_duration, 2),
            "min_duration_ms": round(stats["min_duration_ms"], 2) if stats["min_duration_ms"] != float("inf") else 0,
            "max_duration_ms": round(stats["max_duration_ms"], 2),
        }

    def get_all_stats(self) -> list[dict[str, Any]]:
        """Get stats for all operations."""
        return [self.get_stats(op) for op in self._operations if self.get_stats(op)]

    def reset(self) -> None:
        """Reset all metrics."""
        self._operations.clear()


# Global metrics instance
metrics = OperationMetrics()


def log_operation(operation_name: str, logger: logging.Logger | None = None) -> Callable[[T], T]:
    """
    Decorator to log operation execution with timing and metrics.

    Usage:
        @log_operation("task.create")
        async def create_task(...):
            ...
    """
    def decorator(func: T) -> T:
        _logger = logger or logging.getLogger(func.__module__)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            success = True
            error_msg = None

            with log_context(operation=operation_name):
                _logger.info("Starting %s", operation_name)
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    error_msg = str(e)
                    _logger.exception("Failed %s: %s", operation_name, e)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    metrics.record(operation_name, duration_ms, success)

                    status = "completed" if success else "failed"
                    _logger.info(
                        "%s %s in %.2fms%s",
                        operation_name,
                        status,
                        duration_ms,
                        f" error={error_msg}" if error_msg else "",
                    )

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            success = True
            error_msg = None

            with log_context(operation=operation_name):
                _logger.info("Starting %s", operation_name)
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    error_msg = str(e)
                    _logger.exception("Failed %s: %s", operation_name, e)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    metrics.record(operation_name, duration_ms, success)

                    status = "completed" if success else "failed"
                    _logger.info(
                        "%s %s in %.2fms%s",
                        operation_name,
                        status,
                        duration_ms,
                        f" error={error_msg}" if error_msg else "",
                    )

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def get_correlation_id() -> str:
    """Get current correlation ID from context."""
    return correlation_id_var.get()


def get_context_dict() -> dict[str, str]:
    """Get all context variables as a dictionary."""
    return {
        "correlation_id": correlation_id_var.get(),
        "workspace_id": workspace_id_var.get(),
        "user_id": user_id_var.get(),
        "guild_id": guild_id_var.get(),
        "channel_id": channel_id_var.get(),
        "operation": operation_var.get(),
    }
