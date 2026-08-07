"""
Watering-hole monitor — finds public threads where our buyers describe the
problem we sell against, and queues them for a human reply.

Deliberately standalone: no clients, no accounts, no media, no posts. It
shares nothing with the scraping pipeline but the logging and config helpers.

Flow (see scripts/watch_watering_holes.py):
    sources.fetch_threads   pull newest threads per subreddit (public RSS)
    filtering.prefilter     free keyword gate, drops the bulk
    relevance.score_thread  Gemini relevance 0-100 + draft reply on survivors
    queue.push              upsert into the Notion queue DB, deduped
"""

from __future__ import annotations
