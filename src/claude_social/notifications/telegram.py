"""
Telegram notification helper.

One-way: sends messages to a configured chat/group. Never reads incoming messages.
Failures are logged and swallowed — a notification failure must never crash a pipeline run.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import httpx

from ..config import get_settings
from ..logging import get_logger

log = get_logger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"
_TZ = timezone(timedelta(hours=1))  # UTC+1

# Cron schedule: (job_name, client_slug, hour_utc, minute_utc)
# Posts: weekly Monday. Stories: daily. Times match crontab on VPS.
_SCHEDULE = [
    ("ingest_posts",   "ecig-monitoring",  6, 50),
    ("ingest_posts",   "iluminatecz",      7, 20),
    ("ingest_posts",   "agape",            8,  0),
    ("ingest_stories", "ecig-monitoring",  9, 30),
    ("ingest_stories", "iluminatecz",      9, 50),
    ("ingest_stories", "agape",           10, 15),
]

_JOB_LABEL = {
    "ingest_posts": "Posts",
    "ingest_stories": "Stories",
}


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


def notify_run_scheduled(*, job_name: str, client_name: str, platform: str) -> None:
    send(
        f"🕐 <b>Run scheduled in 1 min</b>\n\n"
        f"Client: {client_name}\n"
        f"Platform: {platform.capitalize()}\n"
        f"Type: {_JOB_LABEL.get(job_name, job_name)}"
    )


def notify_run_started(*, run_id: str, job_name: str, client_name: str, platform: str, account: str | None = None) -> None:
    lines = [
        f"▶️ <b>Run started</b>\n",
        f"Run ID: <code>{run_id[:8]}</code>",
        f"Client: {client_name}",
    ]
    if account:
        lines.append(f"Account: @{account}")
    lines += [
        f"Platform: {platform.capitalize()}",
        f"Type: {_JOB_LABEL.get(job_name, job_name)}",
    ]
    send("\n".join(lines))


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
    job_type = _JOB_LABEL.get(job_name, job_name)

    lines = [
        f"{icon} <b>Run completed</b>\n",
        f"Run ID: <code>{run_id[:8]}</code>",
        f"Client: {client_name}",
    ]
    if account:
        lines.append(f"Account: @{account}")
    lines += [
        f"Platform: {platform.capitalize()}",
        f"Type: {job_type}",
        f"Scraped: {scraped} · New: {new} · Updated: {updated}",
    ]

    if job_name == "ingest_posts" and (ai_gemini + ai_openai + ai_retry) > 0:
        ai_parts = []
        if ai_gemini:
            ai_parts.append(f"{ai_gemini} Gemini")
        if ai_openai:
            ai_parts.append(f"{ai_openai} OpenAI")
        lines.append(f"AI Success: {', '.join(ai_parts)}" if ai_parts else "AI Success: 0")
        if ai_retry:
            retry_time = _next_time_str(minutes=30)
            lines.append(f"🔄 AI retry in 30 min ({retry_time}) — {ai_retry} posts")

    next_same = _next_run_of(job_name, client_slug)
    if next_same:
        lines.append(f"\nNext {job_type} · {client_name}: {next_same}")

    send("\n".join(lines))

    # Separate "next scheduled run across all clients" message
    next_any = _next_run_any(exclude_job=job_name, exclude_slug=client_slug)
    if next_any:
        send(f"⏭ <b>Next scheduled run:</b> {next_any}")


def notify_ai_retry_scheduled(*, run_id: str, client_name: str, count: int) -> None:
    retry_time = _next_time_str(minutes=30)
    send(
        f"🔄 <b>AI retry in 30 min ({retry_time})</b>\n\n"
        f"Run ID: <code>{run_id[:8]}</code>\n"
        f"Client: {client_name}\n"
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
        f"Run ID: <code>{run_id[:8]}</code>",
        f"Success: {succeeded} · Failed: {failed}",
    ]
    if gemini or openai:
        lines.append(f"Gemini: {gemini} · OpenAI: {openai}")
    if still_pending:
        retry_time = _next_time_str(minutes=30)
        lines.append(f"🔄 {still_pending} still unclassified — retry in 30 min ({retry_time})")
    send("\n".join(lines))


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
        f"Run ID: <code>{run_id[:8]}</code>\n"
        f"Client: {client_name}\n"
        f"Platform: {platform.capitalize()}\n"
        f"Failed posts: {len(post_ids)}\n"
        f"Post IDs: {ids}"
    )


# =========================
# Schedule helpers
# =========================

def _now_local() -> datetime:
    return datetime.now(_TZ)


def _next_time_str(*, minutes: int) -> str:
    t = _now_local() + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def _next_run_of(job_name: str, client_slug: str) -> str | None:
    """Return human-readable time of the next run matching job+client."""
    now = _now_local()
    candidates = [(h, m) for j, s, h, m in _SCHEDULE if j == job_name and s == client_slug]
    if not candidates:
        return None
    return _nearest_future(now, candidates)


def _next_run_any(*, exclude_job: str, exclude_slug: str) -> str | None:
    """Return human-readable label of the next run across all scheduled entries."""
    now = _now_local()
    best_dt: datetime | None = None
    best_label: str | None = None
    for job, slug, h, m in _SCHEDULE:
        if job == exclude_job and slug == exclude_slug:
            continue
        dt = _next_dt(now, h, m)
        if best_dt is None or dt < best_dt:
            best_dt = dt
            label_type = _JOB_LABEL.get(job, job)
            best_label = f"{label_type} · {slug} · {dt.strftime('%H:%M')}"
    return best_label


def _nearest_future(now: datetime, candidates: list[tuple[int, int]]) -> str:
    best = min((_next_dt(now, h, m) for h, m in candidates))
    diff = best - now
    if diff.days == 0:
        return f"today {best.strftime('%H:%M')}"
    if diff.days == 1:
        return f"tomorrow {best.strftime('%H:%M')}"
    return best.strftime("%a %H:%M")


def _next_dt(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
