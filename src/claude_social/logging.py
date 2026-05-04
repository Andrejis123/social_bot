"""
Structured logging with structlog.

One shared configuration, called once at process start. All modules use
`get_logger(__name__)` to obtain a bound logger.
"""

from __future__ import annotations

import logging
import sys

import structlog

from .config import get_settings


def setup_logging() -> None:
    """Configure structlog + stdlib logging. Safe to call multiple times."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[return-value]


def bind_run_context(**ctx: object) -> None:
    """Bind fields (e.g. run_id, client_slug) for every log line in this run."""
    structlog.contextvars.bind_contextvars(**ctx)


def clear_run_context() -> None:
    structlog.contextvars.clear_contextvars()
