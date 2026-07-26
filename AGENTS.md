# AI Learning Factory — guía para agentes de código

Plataforma web que fabrica cursos online con agentes de IA. Monorepo con
backend Python (FastAPI + deepagents/LangGraph) y frontend Next.js.
El plan por fases vive en `docs/PLAN.md`; se implementa fase a fase.

## Comandos

```bash
uv sync                                  # deps Python (workspace: api + agents)
uv run pytest apps/api/tests packages/factory_agents/tests -q   # tests
uv run ruff check . --fix                # lint
cd apps/web && npm run typecheck && npm run build               # frontend
make dev-api / make dev-web              # desarrollo local sin Docker
docker compose up --build                # stack completo (2 contenedores)
```

## Arquitectura (lo esencial)

- **SQLite es la única BD** (WAL): dominio vía SQLAlchemy en
  `apps/api/src/factory_api/models.py`, migraciones Alembic en
  `apps/api/alembic/versions/` (numeradas 0001, 0002…). Checkpoints de
  LangGraph en un SQLite aparte (`data/db/checkpoints.sqlite`).
- **Todo corre en un solo proceso backend**: los jobs largos (agentes, TTS,
  vídeo) van por `factory_api/runner.py` — cola persistida en tabla `jobs`,
  worker asyncio, progreso como `JobEvent`s que la UI consume por SSE.
- **Agentes** en `packages/factory_agents/`: cada uno tiene un `AgentSpec`
  registrado (registry en `runtime.py`) con prompt base + perfil
  (`soul.md`/`agents.md`) editable por el usuario y versionado en BD.
  El prompt se compone base + agents.md + soul.md; el base marca límites.
- **Revisión automática**: vive exclusivamente en el perfil versionado
  (`automatic_review_enabled` + `max_automatic_regenerations`, 0–5). El run
  congela la política; los workflows no declaran ni permiten `evaluate`.
- **Aprobación humana**: vive exclusivamente en el perfil versionado
  (`human_review_enabled`, desactivada por defecto). El workflow congela la
  política, ignora `approval_after` histórico y el feedback regenera la misma
  fase desde un nodo separado antes de volver a pedir aprobación.
- **Contratos de artefactos** en `factory_agents/contracts/`: los tipos
  (course_idea_brief, research_brief, course_plan, lesson_content,
  slide_deck…) son la columna vertebral — los agentes declaran consumes/
  produces y el pipeline se conecta por artefactos persistidos en
  `data/artifacts/` con metadatos en la tabla `artifacts`.
- **Workflows**: cadenas lineales declarativas (JSON) compiladas a LangGraph
  en `factory_api/workflow_engine.py`; las aprobaciones humanas usan
  `interrupt()` en nodos separados del nodo de agente (al reanudar, LangGraph
  re-ejecuta el nodo desde el principio — nunca pongas interrupt en el mismo
  nodo que una llamada cara).
- **Duración de curso**: `duration_spec` vive en brief/proyecto, fija módulos,
  lecciones y minutos, y se inyecta como presupuesto derivado en Curator,
  Planner, Lessons, Slides, Script y Voice. Los proyectos históricos sin ella
  no pueden iniciar `planner` ni fases posteriores.
- **Editor de workflows**: los workflows editables empiezan siempre por
  `curator`. La compatibilidad entre pasos depende de los artefactos disponibles
  y se define en `apps/web/src/lib/workflowRules.ts`; debe mantenerse alineada
  con `AGENT_INPUTS`/`AGENT_OUTPUTS` de `factory_api/workflow_engine.py`.
- **LLM**: OpenRouter (OpenAI-compatible), modelo por defecto en
  `Settings.openrouter_model`. Los agentes conversacionales (ideación) usan
  el cliente openai directo; los task agents usan deepagents.
- **Renderizado web**: usa el componente `Markdown` para contenido generado y
  notas de memoria. Los artefactos JSON se muestran con `JsonViewer`; conserva
  la descarga raw, pero no presentes JSON sin procesar como vista principal.
- **Orientación multimedia**: los perfiles de `slides` y `video` guardan
  `orientation` (`horizontal` por defecto o `vertical`). Las variantes de vídeo
  siguen en la misma familia versionada y registran la orientación en los
  metadatos del artefacto; no dupliques subtítulos si su contenido no cambia.
  Las slides verticales usan el tema Marp `factory-vertical` con canvas nativo
  1080×1920 en HTML/PDF/PPTX/PNG; un PPTX conjunto nunca mezcla orientaciones.
- **Imágenes de slides**: son opcionales y se configuran/versionan en el perfil
  de `slides` (modelo OpenRouter + preset o prompt personalizado). El agente
  selecciona como máximo 6 por lección; los originales viven como assets de la
  versión del `slide_deck` y prompts/modelo/coste quedan en sus metadatos. Una
  regeneración individual siempre crea una nueva versión autosuficiente del deck.
- **Paletas de slides**: los ocho colores viven en el perfil versionado y se
  aplican mediante el bloque CSS canónico de `tools/palette.py` dentro del
  Markdown Marp. Cambiar una paleta crea nuevas versiones autosuficientes,
  clona assets y vuelve a renderizar sin llamar a LLM ni regenerar imágenes.
- **Logos de slides**: la biblioteca y presentación viven en el perfil
  versionado. El run copia el logo activo a cada versión del `slide_deck` y lo
  inyecta con `tools/logos.py`; nunca lo regenera durante la producción.

## Convenciones

- UI en español; código, comentarios y commits en inglés.
- En ideación, cada turno anterior al brief final termina con
  `ask_user_question` y varias opciones clicables; la UI mantiene siempre una
  última opción de texto libre. No añadas otra pregunta al presentar el brief.
- Tests de API con TestClient + agentes falseados vía monkeypatch de
  `factory_agents.agents.<x>.run_<x>` (import lazy en runner para permitirlo).
- En tests, los env vars se fijan en `tests/conftest.py` ANTES de importar
  la app (no reordenar esos imports).
- Ejecutar siempre ruff + pytest + typecheck antes de commitear; push a la
  rama de trabajo al cerrar cada fase.
