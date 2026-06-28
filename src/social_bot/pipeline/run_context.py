"""
Context manager that bookkeeps a pipeline run in the `run_history` table.

Usage:
    with RunContext(job_name="ingest_posts", client_slug="foo", account_handle="nike") as run:
        run.items_total = len(items)
        for item in items:
            try:
                _process(item)
                run.items_new += 1
            except Exception as exc:
                run.record_item_error(item.ref, stage="ai", message=str(exc))

On exit, the row is finalised as 'success' / 'partial' / 'failed' and log
context is cleared. A fatal exception bubbles up unchanged.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from ..db import queries
from ..logging import bind_run_context, clear_run_context, get_logger

log = get_logger(__name__)


@dataclass
class RunContext:
    job_name: str
    client_slug: str | None
    account_handle: str | None = None
    platform: str = "instagram"

    silent: bool = False  # suppress Telegram notifications (run_history still recorded)

    run_id: str = ""
    items_total: int = 0
    items_new: int = 0
    items_updated: int = 0
    items_failed: int = 0
    items_ai_retry: int = 0
    ai_gemini_count: int = 0
    ai_openai_count: int = 0
    _fatal_summary: str | None = field(default=None, init=False)

    def __enter__(self) -> Self:
        self.run_id = queries.start_run(
            job_name=self.job_name,
            client_slug=self.client_slug,
            account_handle=self.account_handle,
        )
        bind_run_context(
            run_id=self.run_id,
            job=self.job_name,
            client=self.client_slug,
            account=self.account_handle,
        )
        log.info("run.start")
        self._notify_started()
        return self

    def _notify_started(self) -> None:
        if self.silent:
            return
        try:
            from ..notifications.telegram import notify_run_started
            notify_run_started(
                run_id=self.run_id,
                job_name=self.job_name,
                client_name=self.client_slug or "unknown",
                platform=self.platform,
                account=self.account_handle,
            )
        except Exception as exc:
            log.warning("run.notification_failed", error=str(exc))

    def record_item_error(
        self,
        item_ref: str | None,
        *,
        stage: str,
        message: str,
    ) -> None:
        """Record a per-item failure. Does not raise — lets the loop continue."""
        self.items_failed += 1
        try:
            queries.record_item_error(
                self.run_id, item_ref=item_ref, stage=stage, error_message=message
            )
        except Exception as exc:
            # Logging the error table failure would be ironic; just emit a log.
            log.error("run.item_error.record_failed", error=str(exc))
        log.warning("run.item_error", item=item_ref, stage=stage, message=message)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if exc_val is not None:
            self._fatal_summary = f"{exc_type.__name__}: {exc_val}\n{''.join(traceback.format_tb(exc_tb))}"
            status = "failed"
        elif self.items_failed == 0:
            status = "success"
        elif self.items_new + self.items_updated > 0:
            status = "partial"
        else:
            status = "failed"

        try:
            queries.finish_run(
                self.run_id,
                status=status,
                items_total=self.items_total,
                items_new=self.items_new,
                items_updated=self.items_updated,
                items_failed=self.items_failed,
                error_summary=self._fatal_summary,
            )
        except Exception as exc:
            log.error("run.finish.failed", error=str(exc))

        log.info(
            "run.finish",
            status=status,
            total=self.items_total,
            new=self.items_new,
            updated=self.items_updated,
            failed=self.items_failed,
        )
        clear_run_context()
        self._send_notification(status)
        return False  # do not swallow exceptions

    def _send_notification(self, status: str) -> None:
        if self.silent and status == "success":
            return
        try:
            from ..notifications.telegram import notify_run_completed
            notify_run_completed(
                run_id=self.run_id,
                job_name=self.job_name,
                client_slug=self.client_slug or "",
                client_name=self.client_slug or "unknown",
                platform=self.platform,
                status=status,
                scraped=self.items_total,
                new=self.items_new,
                updated=self.items_updated,
                ai_gemini=self.ai_gemini_count,
                ai_openai=self.ai_openai_count,
                ai_retry=self.items_ai_retry,
                account=self.account_handle,
            )
        except Exception as exc:
            log.warning("run.notification_failed", error=str(exc))
