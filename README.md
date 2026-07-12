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

## Qué hay implementado

- **Asistente de Ideación** (`/ideation`): conversa sobre una idea vaga con
  preguntas de 3-4 opciones hasta producir un brief que se convierte en proyecto.
- **Agentes de contenido**: Curador (investigación web con fuentes), Diseñador
  de curso (plan estructurado), Generador de lecciones (verifica el código en
  sandbox) y Diseñador de slides (Marp → HTML/PDF/PPTX).
- **Perfiles** (`/profiles`): cada agente se configura con `soul.md` +
  `agents.md`, con versionado y varios perfiles por agente.
- **Workflows** (`/workflows`): cadenas de agentes editables (React Flow) con
  pausas de aprobación humana; motor LangGraph con checkpoints en SQLite
  (pausar, aprobar/rechazar con feedback, reanudar incluso tras reinicio).
- **Artefactos**: todas las salidas son artefactos versionados y descargables;
  puedes subir material propio (p. ej. tus slides) como punto de entrada.

## Estructura

```
apps/api/                  # FastAPI: REST + SSE, auth, jobs, workflows (LangGraph)
apps/web/                  # Next.js: UI (español)
packages/factory_agents/   # Agentes, herramientas, contratos de artefactos
docs/PLAN.md               # Plan de implementación por fases
```
