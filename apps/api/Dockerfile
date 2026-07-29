# Build context is the repo root (the API depends on packages/factory_agents).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS sandbox-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev \
    && rm -rf /var/lib/apt/lists/*
COPY apps/api/sandbox_launcher.c /tmp/sandbox_launcher.c
RUN gcc -O2 -Wall -Wextra -Werror \
    /tmp/sandbox_launcher.c -lseccomp -o /usr/local/bin/python-sandbox-launcher

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ffmpeg (video), Chromium + Node (marp-cli slide rendering), fonts and the
# seccomp runtime all live here to keep the promise of one backend container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core chromium libseccomp2 nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @marp-team/marp-cli \
    && npm cache clean --force
COPY --from=sandbox-builder \
    /usr/local/bin/python-sandbox-launcher /usr/local/bin/python-sandbox-launcher

ENV CHROME_PATH=/usr/bin/chromium

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/factory_agents packages/factory_agents
COPY apps/api apps/api

RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1

ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid "${APP_GID}" factory \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
        --create-home --home-dir /home/factory --shell /usr/sbin/nologin factory \
    && mkdir -p /data/db /data/artifacts /data/tmp \
    && chown -R "${APP_UID}:${APP_GID}" /data /home/factory
ENV HOME=/home/factory

WORKDIR /app/apps/api
EXPOSE 8000
USER factory:factory
CMD ["sh", "-c", "alembic upgrade head && uvicorn factory_api.main:app --host 0.0.0.0 --port 8000"]
