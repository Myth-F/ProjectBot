from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
workspace_id_var: ContextVar[str] = ContextVar("workspace_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")
guild_id_var: ContextVar[str] = ContextVar("guild_id", default="-")
channel_id_var: ContextVar[str] = ContextVar("channel_id", default="-")


_base_factory = logging.getLogRecordFactory()
_factory_set = False


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    record = _base_factory(*args, **kwargs)
    record.correlation_id = correlation_id_var.get()
    record.workspace_id = workspace_id_var.get()
    record.user_id = user_id_var.get()
    record.guild_id = guild_id_var.get()
    record.channel_id = channel_id_var.get()
    return record


def configure_logging(level: str) -> None:
    global _factory_set
    if not _factory_set:
        logging.setLogRecordFactory(_record_factory)
        _factory_set = True

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "correlation_id=%(correlation_id)s workspace_id=%(workspace_id)s "
            "user_id=%(user_id)s guild_id=%(guild_id)s channel_id=%(channel_id)s"
        ),
    )


@contextmanager
def log_context(
    *,
    correlation_id: str | None = None,
    workspace_id: str | None = None,
    user_id: str | None = None,
    guild_id: str | None = None,
    channel_id: str | None = None,
) -> Iterator[None]:
    tokens = {}
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
    try:
        yield
    finally:
        for var, token in tokens.items():
            var.reset(token)
