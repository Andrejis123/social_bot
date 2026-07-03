"""
Telegram notification helper.

One-way: sends messages to a configured chat/group. Never reads incoming messages.
Failures are logged and swallowed — a notification failure must never crash a pipeline run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..config import get_settings
from ..logging import get_logger

log = get_logger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"
_TZ = timezone(timedelta(hours=1))  # UTC+1

_JOB_LABEL = {
    "ingest_posts": "Posts",
    "ingest_stories": "Stories",
    "describe_posts": "AI Descriptions",
    "describe_stories": "AI Descriptions",
}


def _label(job_name: str) -> str:
    return _JOB_LABEL.get(job_name, job_name)


def send(text: str) -> None:
    """Send an HTML-formatted message. Silently no-ops if not configured."""
    settings = get_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return
    try:
        with httpx.Client(timeout=10.0) as http:
            resp = http.post(
                _API.format(token=token),
                data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
    except Exception as exc:
        log.warning("telegram.send_failed", error=str(exc))


def notify_run_started(
    *,
    run_id: str,
    job_name: str,
    client_name: str,
    platform: str,
    account: str | None = None,
) -> None:
    label = _label(job_name)
    handle = f"@{account}" if account else client_name
    send(
        f"▶️ <b>Run started</b>\n\n"
        f"<code>{run_id[:8]}</code> · {handle} · {label}"
    )


def notify_run_completed(
    *,
    run_id: str,
    job_name: str,
    client_slug: str,
    client_name: str,
    platform: str,
    status: str,
    scraped: int,
    new: int,
    updated: int,
    ai_gemini: int,
    ai_openai: int,
    ai_retry: int,
    account: str | None = None,
) -> None:
    icon = {"success": "✅", "partial": "⚠️", "failed": "❌"}.get(status, "ℹ️")
    label = _label(job_name)
    handle = f"@{account}" if account else client_name

    # Describe jobs don't scrape and never increment `updated` — relabel so
    # the same counters read sensibly. items_total = queue size found in DB,
    # items_new = how many got newly described.
    if job_name in ("describe_posts", "describe_stories"):
        counters_line = f"Found: {scraped} · Described: {new}"
    else:
        counters_line = f"Scraped: {scraped} · New: {new} · Updated: {updated}"

    lines = [
        f"{icon} <b>Run completed</b>\n",
        f"<code>{run_id[:8]}</code> · {handle} · {label}",
        counters_line,
    ]

    if job_name in ("ingest_posts", "ingest_stories") and (ai_gemini + ai_openai + ai_retry) > 0:
        ai_parts = []
        if ai_gemini:
            ai_parts.append(f"{ai_gemini} Gemini")
        if ai_openai:
            ai_parts.append(f"{ai_openai} OpenAI")
        if ai_parts:
            lines.append(f"AI: {', '.join(ai_parts)}")
        if ai_retry:
            lines.append(f"🔄 {ai_retry} pending retry")

    send("\n".join(lines))


def notify_run_scheduled(*, job_name: str, client_name: str, platform: str) -> None:
    label = _label(job_name)
    send(f"🕐 <b>Run scheduled in 1 min</b> · {client_name} · {label}")


def notify_ai_retry_scheduled(*, run_id: str, client_name: str, count: int) -> None:
    t = (datetime.now(_TZ) + timedelta(minutes=30)).strftime("%H:%M")
    send(
        f"🔄 <b>AI retry in 30 min ({t})</b>\n\n"
        f"<code>{run_id[:8]}</code> · {client_name}\n"
        f"Posts to retry: {count}"
    )


def notify_ai_retry_completed(
    *,
    run_id: str,
    succeeded: int,
    failed: int,
    gemini: int,
    openai: int,
    still_pending: int,
) -> None:
    icon = "✅" if failed == 0 else "⚠️"
    lines = [
        f"🔄 <b>AI retry completed</b> {icon}\n",
        f"<code>{run_id[:8]}</code>",
        f"Success: {succeeded} · Failed: {failed}",
    ]
    if gemini or openai:
        lines.append(f"Gemini: {gemini} · OpenAI: {openai}")
    if still_pending:
        t = (datetime.now(_TZ) + timedelta(minutes=30)).strftime("%H:%M")
        lines.append(f"🔄 {still_pending} still pending — retry at {t}")
    send("\n".join(lines))


def notify_report_generated(
    *,
    client_name: str,
    period_label: str,
    slide_count: int,
    bytes_size: int,
    signed_url: str,
) -> None:
    """Ping when a report .pptx has been rendered and uploaded to Supabase."""
    size_mb = bytes_size / (1024 * 1024)
    send(
        f"📊 <b>Report generated</b>\n\n"
        f"{client_name} · {period_label}\n"
        f"{slide_count} slides · {size_mb:.1f} MB\n"
        f'<a href="{signed_url}">Download .pptx</a>'
    )


def notify_report_failed(
    *,
    client_slug: str,
    period_label: str,
    error: str,
) -> None:
    """Ping when a client's report failed to generate after its retries.

    An ops alert (not a client-facing content notification), so it names the
    client slug rather than the report-subject @handle.
    """
    send(
        f"⚠️ <b>Report failed</b>\n\n"
        f"{client_slug} · {period_label}\n"
        f"<code>{error}</code>"
    )


def notify_archive_completed(
    *,
    client_slug: str,
    period_label: str,
    breakdown: str,
    size_mb: float,
    drive_link: str,
) -> None:
    """Ping when a client's period was archived to Drive and verified.

    Ops alert. `breakdown` is the per-account posts/stories/files text from
    storage.summary.render_summary.
    """
    link = f'<a href="{drive_link}">zip in Drive</a>' if drive_link else "zip in Drive"
    send(
        f"📦 <b>Archived</b>\n\n"
        f"{client_slug} · {period_label} · {size_mb:.1f} MB\n"
        f"{breakdown}\n"
        f"{link}"
    )


def notify_archive_failed(*, client_slug: str, error: str) -> None:
    """Ping when a client's archive aborted (partial bundle, upload mismatch...)."""
    send(
        f"⚠️ <b>Archive failed</b>\n\n"
        f"{client_slug}\n"
        f"<code>{error}</code>"
    )


def notify_purge_completed(*, client_label: str, breakdown: str) -> None:
    """Ping when archived, grace-expired media was purged from the bucket.

    `breakdown` is the per-account posts/stories/files text from
    storage.summary.render_summary.
    """
    send(
        f"🗑 <b>Purged</b>\n\n"
        f"{client_label}\n"
        f"{breakdown}"
    )


def notify_purge_failed(*, client_label: str, error: str) -> None:
    """Ping when a purge failed mid-run (storage delete or tombstone raised)."""
    send(
        f"⚠️ <b>Purge failed</b>\n\n"
        f"{client_label}\n"
        f"<code>{error}</code>"
    )


def notify_ai_exhausted(
    *,
    run_id: str,
    client_name: str,
    platform: str,
    post_ids: list[str],
) -> None:
    ids = ", ".join(f"<code>{p[:8]}</code>" for p in post_ids)
    send(
        f"❌ <b>AI classification failed — 3 attempts exhausted</b>\n\n"
        f"<code>{run_id[:8]}</code> · {client_name}\n"
        f"Failed: {len(post_ids)} posts\n"
        f"IDs: {ids}"
    )
