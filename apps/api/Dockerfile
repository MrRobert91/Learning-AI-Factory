# Build context is the repo root (the API depends on packages/factory_agents).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ffmpeg and fonts are needed by later phases (video rendering); installing
# them here keeps the promise of a single backend image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/factory_agents packages/factory_agents
COPY apps/api apps/api

RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/apps/api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn factory_api.main:app --host 0.0.0.0 --port 8000"]
