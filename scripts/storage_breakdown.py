"""Storage usage breakdown: `python -m scripts.storage_breakdown`.

Walks the Supabase Storage media bucket and prints a point-in-time breakdown of
what occupies the 1 GB free-tier cap, by client and by kind (posts vs stories).
The only authoritative answer to "what is eating my storage", since story media
carries no size column in the DB and the dashboard shows only a lagging average.
"""

from __future__ import annotations

import logging

from social_bot.logging import setup_logging
from social_bot.storage.usage import compute_storage_breakdown, format_storage_breakdown


def main() -> None:
    setup_logging()
    # The bucket walk makes hundreds of list calls; mute per-request httpx INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(format_storage_breakdown(compute_storage_breakdown()))


if __name__ == "__main__":
    main()
