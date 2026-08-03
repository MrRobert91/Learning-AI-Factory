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
- **Eventos de jobs**: `factory_api.events.EventRepository` es el único escritor.
  Reserva `jobs.next_event_seq` e inserta el evento en la misma transacción;
  nunca recuperes `max(seq)` ni hagas commit dentro de un helper anidado. El
  SSE consulta `(job_id, seq)` por lotes, reanuda con `Last-Event-ID` y espera
  el broker local entre commits; SQLite sigue siendo la fuente persistente.
  Todo endpoint por `job_id` debe usar `get_owned_job`, y los jobs globales sin
  proyecto no se exponen al propietario por defecto.
- **Pausa/cancelación de jobs**: son cooperativas y persistidas en
  `jobs.control_json`. Cada handler debe consultar `run_control.checkpoint()`
  antes/después de sus unidades caras y registrar unidades completas para que
  reanudar no repita agentes, lecciones, renders, TTS ni ffmpeg terminados.
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
- **Fuentes de ideación**: cada URL/documento se captura una vez, se extrae en
  backend y conserva hash + IDs estables al pasar de sesión a proyecto.
  `provided_only` no expone herramientas web y obliga a citas
  `[source:<id> <ubicación>]`; Curator reutiliza el mismo corpus y política sin
  volcar documentos completos al prompt.
- **Editor de workflows**: los workflows editables empiezan siempre por
  `curator`. La compatibilidad entre pasos depende de los artefactos disponibles
  y se define una sola vez en
  `packages/factory_agents/src/factory_agents/contracts/agent_io.json`;
  `factory_api.workflow_engine` la consume directamente y el contexto Docker
  aislado de web usa `apps/web/src/lib/agent_io.generated.json`, un espejo cuya
  igualdad exacta exige la suite backend. `workflowRules.ts` consume ese espejo.
  Las acciones contextuales de las tarjetas congelan los IDs seleccionados al
  crear el job, rechazan una selección obsoleta y restauran la selección de
  outputs anterior si una regeneración falla o se cancela.
- **Workflow seleccionado**: `projects.selected_workflow_id` conserva la
  preferencia mutable de cada proyecto. La UI solo usa un fallback temporal si
  falta o dejó de estar disponible; cada run congela por separado su ID, nombre
  y definición, y nunca se reescribe al cambiar la preferencia del proyecto.
- **Versión activa de perfiles**: `AgentProfile.version` es la última versión
  monotónica y `active_version` apunta al snapshot usado por futuras
  ejecuciones. Activar una versión histórica no crea otra versión; los campos
  actuales reflejan ese snapshot y editarlo crea la siguiente versión máxima,
  que pasa a ser activa. Cada run congela la versión activa y su configuración.
- **LLM**: OpenRouter (OpenAI-compatible), modelo por defecto en
  `Settings.openrouter_model`. Los agentes conversacionales (ideación) usan
  el cliente openai directo; los task agents usan deepagents.
- **Renderizado web**: usa el componente `Markdown` para contenido generado y
  notas de memoria. Los artefactos JSON se muestran con `JsonViewer`; conserva
  la descarga raw, pero no presentes JSON sin procesar como vista principal.
- **Cronología de artefactos**: `GET /api/projects/{project_id}/artifacts`
  devuelve solo las versiones seleccionadas en orden global
  `created_at DESC, id DESC`; la UI conserva ese orden sin agrupar por tipo y el
  historial de cada familia se mantiene por versión descendente.
- **Orientación multimedia**: los perfiles de `slides` y `video` guardan
  `orientation` (`horizontal` por defecto o `vertical`). Las variantes de vídeo
  siguen en la misma familia versionada y registran la orientación en los
  metadatos del artefacto; no dupliques subtítulos si su contenido no cambia.
  Las slides verticales usan el tema Marp `factory-vertical` con canvas nativo
  1080×1920 en HTML/PDF/PPTX/PNG; un PPTX conjunto nunca mezcla orientaciones.
- **Voz y subtítulos**: el perfil versionado de `voice` es la fuente de verdad
  para proveedor/modelo/idioma/voz TTS. Cada `voice_script` congela la
  combinación efectiva y vídeo debe consumir ese snapshot, no la configuración
  global mutable. El formato de request, MIME, sample rate y canales se resuelven
  desde capacidades por modelo; Gemini PCM se normaliza a WAV antes de preview,
  caché y ffmpeg, sin etiquetarlo como MP3. El perfil de `video` guarda
  `subtitles_mode` (`none` por
  defecto, `srt` o `burned_and_srt`); la incrustación usa duraciones TTS reales,
  respeta orientación/logos y nunca añade llamadas LLM.
- **Catálogo y expresividad TTS**: OpenRouter se descubre mediante Models API y
  se conserva en un snapshot backend con TTL y fallback al último válido; las
  voces documentadas completan metadata incompleta del API. Solo se muestran y
  envían controles declarados por el modelo (`speed`, instrucciones, estilo,
  intensidad, tags/pronunciación). El perfil versiona esas opciones, el
  `voice_script` congela entrada de catálogo/precio/configuración y la clave de
  caché incluye toda opción audible; una combinación retirada bloquea runs
  nuevos, pero vídeo sigue consumiendo snapshots históricos autosuficientes.
- **Vídeo completo del curso**: `course_video_export` consume el `course_plan` y
  las versiones seleccionadas de `video`/`subtitles` en orden pedagógico. El
  preflight bloquea inputs ausentes, corruptos o incompatibles antes de ffmpeg;
  el job concatena sin LLM/TTS, ajusta SRT/capítulos a la transición, valida la
  salida con ffprobe y solo entonces publica `course_video` y sus asociados
  versionados. Inputs y opciones idénticos reutilizan la versión válida.
- **FFmpeg**: toda recodificación `libx264` usa la política efectiva
  `FFMPEG_THREADS`/`FFMPEG_FILTER_THREADS`/`FFMPEG_FILTER_COMPLEX_THREADS`,
  `FFMPEG_PRESET` y `FFMPEG_CRF`. La composición de lecciones precompone una
  imagen estática cuando necesita fondo, publica cada segmento MP4 de forma
  atómica con firma/manifiesto y `ffprobe`, y el runner debe pasar control
  cooperativo para terminar el grupo FFmpeg activo al pausar o cancelar.
- **Imágenes de slides**: son opcionales y se configuran/versionan en el perfil
  de `slides` (modelo OpenRouter + preset o prompt personalizado). El agente
  selecciona como máximo 6 por lección y solo puede pedir composición lateral
  `left`/`right`; `background` o cualquier layout automático inválido se
  normaliza a `right`, conservando requested/effective layout en metadatos. Los
  fondos explícitos históricos/importados siguen siendo compatibles. Los
  originales viven como assets de la versión del `slide_deck` y
  prompts/modelo/coste quedan en sus metadatos. Una regeneración individual
  conserva el lateral y siempre crea una nueva versión autosuficiente del deck.
- **Uso y costes**: cada llamada LLM/evaluador/imagen/TTS se registra una sola
  vez en `usage_records` sin prompts ni respuestas. El histórico es inmutable;
  el coste activo se deriva de `usage_record_ids` en los artefactos seleccionados,
  y real/estimado/desconocido nunca se mezclan ni se presentan como equivalentes.
- **Paletas de slides**: los ocho colores viven en el perfil versionado y se
  aplican mediante el bloque CSS canónico de `tools/palette.py` dentro del
  Markdown Marp. Cambiar una paleta crea nuevas versiones autosuficientes,
  clona assets y vuelve a renderizar sin llamar a LLM ni regenerar imágenes.
- **Logos de slides**: la biblioteca y presentación viven en el perfil
  versionado. El run copia el logo activo a cada versión del `slide_deck` y lo
  inyecta con `tools/logos.py` como capa absoluta respecto al canvas; una imagen
  lateral nunca cambia su esquina. `logo_background_mode` es `opaque` por
  defecto o `transparent`: este último conserva el original, reutiliza un PNG
  RGBA derivado y validado, y congela ambos hashes/asset efectivo en el snapshot.
  Nunca elimines el fondo ni regeneres el logo durante la producción.

- **Seguridad de dependencias**: CI bloquea vulnerabilidades `high`/`critical`
  con `npm run audit:prod`, `npm run audit:all` y `pip-audit==2.10.1` sobre el
  export congelado de uv. Mantén Next.js en la serie 15 y React en la 19 hasta
  una migración explícita; los overrides de PostCSS/Sharp son parches
  documentados y deben retirarse cuando Next los incorpore. Dependabot propone
  actualizaciones semanales a `dev`, sin auto-merge.
- **Sandbox de Python**: el código generado se ejecuta con
  `PYTHON_SANDBOX_MODE=isolated` bajo Landlock + seccomp, sin acceso a `/app` o
  `/data` y sin syscalls de red/procesos/namespaces; el backend Docker corre
  como usuario no root. Fuera de Docker el valor seguro es `disabled`;
  `local-unsafe` debe elegirse explícitamente y nunca es fallback de un
  aislamiento fallido.

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
