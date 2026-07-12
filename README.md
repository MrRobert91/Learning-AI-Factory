# AI Learning Factory

Plataforma web para automatizar la creación de cursos online mediante un sistema modular de agentes de IA. Una "fábrica de cursos" donde agentes especializados colaboran para transformar una idea en materiales educativos completos: plan del curso, contenidos, diapositivas, guiones docentes, narración con voz IA, vídeos y publicación en YouTube.

📋 **Plan de implementación completo:** [docs/PLAN.md](docs/PLAN.md)

## Arranque rápido (Docker, 2 contenedores)

```bash
cp .env.example .env   # ajusta APP_PASSWORD y SECRET_KEY
docker compose up --build
```

- Frontend: http://localhost:3000
- API (docs OpenAPI): http://localhost:8000/docs

Los datos persisten en `./data` (SQLite, artefactos y memoria de agentes).

## Desarrollo sin Docker

Requisitos: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 22+.

```bash
uv sync                                  # backend + paquete de agentes
cd apps/web && npm install && cd ../..   # frontend

make dev-api    # FastAPI en :8000 (aplica migraciones primero)
make dev-web    # Next.js en :3000 (proxy /api → :8000)
```

Tests y lint: `make test` · `make lint`

## Estructura

```
apps/api/                  # FastAPI: REST + SSE, auth, dominio
apps/web/                  # Next.js: UI (español)
packages/factory_agents/   # Agentes, herramientas, orquestación, contratos
docs/PLAN.md               # Plan de implementación por fases
```
