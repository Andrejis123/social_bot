# Social_Bot runtime image — Python 3.12 + uv for dependency install.
# Build from the repo root:  docker build -f docker/Dockerfile -t social-bot .
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv

# Install uv (fast Python package manager) + minimal system deps.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Install deps first — this layer caches until pyproject.toml/uv.lock change.
# --frozen with a committed uv.lock: a lockfile mismatch fails the build loudly
# instead of silently resolving fresh dependency versions on every deploy.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Copy everything else (scripts, config, migrations, brand assets).
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY migrations/ ./migrations/
COPY assets/ ./assets/

# Default: print help. Override with `docker run ... python -m scripts.scrape_posts ...`
ENTRYPOINT ["uv", "run", "--no-sync", "--"]
CMD ["python", "-m", "scripts.scrape_posts", "--help"]
