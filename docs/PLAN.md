# Plan de implementación — AI Learning Factory

> Plataforma web para automatizar la creación de cursos online mediante un harness agentico modular basado en LangChain/LangGraph (deep agents + OpenWiki Brains).

---

## 1. Visión y objetivos

**Qué es:** una "fábrica de cursos" donde agentes de IA especializados colaboran para transformar una idea ("curso de introducción a los LLMs") en materiales educativos completos: plan del curso, contenidos, diapositivas, guiones docentes, narración con voz IA, vídeos y publicación en YouTube.

**Objetivo doble:**
1. Herramienta real para producir cursos técnicos de alta calidad (IA, tecnología, computación cuántica).
2. Demostración avanzada de ingeniería IA: orquestación, modularidad, memoria, herramientas, evaluación, guardarraíles y automatización multimodal en una aplicación web completa.

**Principio de diseño central:** no es un pipeline cerrado, sino un **harness agentico modular**. Cada agente es utilizable de forma independiente o conectado a otros en workflows editables. El usuario puede parar tras las slides, generar solo un guion a partir de slides existentes, o ejecutar el flujo completo hasta el vídeo publicado.

---

## 2. Alcance y fases (resumen ejecutivo)

| Fase | Nombre | Entregable clave |
|------|--------|------------------|
| 0 | Fundaciones | Monorepo, CI, infraestructura local (Docker Compose), esqueleto API + web |
| 1 | Núcleo agentico | Runtime de agentes (deep agents), sistema `soul.md`/`agents.md` + perfiles, primer agente end-to-end (Curador) |
| 2 | Pipeline de contenido | Agentes Diseñador de curso, Generador de lecciones y Slides; artefactos versionados |
| 3 | Orquestación de workflows | Motor LangGraph con grafos editables, pausa/reanudación, human-in-the-loop, editor visual |
| 4 | Multimodal | Guion docente, adaptación a voz, TTS, montaje de vídeo (ffmpeg/Remotion) |
| 5 | Publicación y memoria avanzada | Agente Publicador YouTube, OpenWiki Brains como memoria de proyecto/usuario |
| 6 | Calidad y producción | Evaluadores automáticos, guardarraíles, observabilidad (LangSmith), despliegue |

Cada fase termina con algo demostrable en la web app. El detalle está en la sección 10.

---

## 3. Arquitectura general

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                        │
│  - Proyectos, editor de workflows (React Flow),            │
│    editor de perfiles soul.md/agents.md, visor de          │
│    artefactos, panel de ejecución en tiempo real           │
└──────────────┬─────────────────────────────────────────────┘
               │ REST + SSE/WebSocket
┌──────────────▼─────────────────────────────────────────────┐
│  API Backend (FastAPI, Python)                             │
│  - Auth, CRUD proyectos/workflows/perfiles                 │
│  - Lanzamiento y control de ejecuciones                    │
│  - Streaming de eventos de agentes                         │
└──────┬──────────────────────────────┬──────────────────────┘
       │                              │
┌──────▼──────────────┐   ┌───────────▼────────────────────┐
│  Orquestador        │   │  Workers (cola: Redis/arq)     │
│  LangGraph          │   │  - Ejecución de agentes        │
│  - Grafo por        │   │  - Tareas pesadas: TTS,        │
│    workflow         │   │    render vídeo, subida YT     │
│  - Checkpointer     │   └───────────┬────────────────────┘
│    (Postgres)       │               │
│  - interrupts (HITL)│               │
└──────┬──────────────┘               │
       │                              │
┌──────▼──────────────────────────────▼──────────────────────┐
│  Capa de datos y memoria                                   │
│  - Postgres: dominio + checkpoints LangGraph               │
│  - S3/MinIO: artefactos (md, pptx/html, mp3, mp4, png)     │
│  - Memoria de agentes: filesystem-backed (deep agents)     │
│    + wiki de proyecto estilo OpenWiki Brains               │
│  - Redis: cola de trabajos y pub/sub de eventos            │
└────────────────────────────────────────────────────────────┘
```

**Decisiones clave:**

- **Backend en Python** (FastAPI): el ecosistema deep agents / LangGraph es Python-first; TTS, ffmpeg y evaluación también.
- **Ejecuciones largas fuera del ciclo request/response**: cada ejecución de workflow corre en un worker; la API solo lanza, consulta estado y retransmite eventos vía SSE.
- **LangGraph como motor de workflows**: los grafos se construyen dinámicamente a partir de una definición declarativa (JSON) editable desde la UI. Checkpointer en Postgres da pausa/reanudación, reintentos y time-travel gratis.
- **Cada agente = subgrafo/nodo `deepagents`**: con sus herramientas, su memoria (backend de ficheros) y su configuración de personalidad inyectada como system prompt desde `soul.md` + `agents.md`.
- **Artefactos como ciudadanos de primera clase**: toda salida (outline, lección, slides, guion, audio, vídeo) es un artefacto versionado en S3 con metadatos en Postgres. Esto permite entrar al pipeline por cualquier punto (p. ej. subir slides propias y generar solo el guion).

---

## 4. Stack tecnológico propuesto

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| Frontend | Next.js 15 + TypeScript, Tailwind, shadcn/ui | Productividad, SSR, ecosistema |
| Editor de workflows | React Flow (xyflow) | Estándar de facto para editores de grafos |
| Editor de soul.md/agents.md | CodeMirror/Monaco con preview Markdown | Edición cómoda de perfiles |
| API | FastAPI + Pydantic v2 | Async, tipado, OpenAPI automático |
| Agentes | `deepagents` + LangChain + LangGraph | Requisito del proyecto; planificación, sub-agentes y memoria en ficheros integrados |
| LLMs | Claude (Anthropic) como principal; capa de abstracción `init_chat_model` para intercambiar proveedor por agente | Calidad en escritura larga y razonamiento pedagógico |
| Memoria | Backends de filesystem de deep agents + wiki de proyecto (patrón OpenWiki Brains) | Ver sección 7 |
| Base de datos | PostgreSQL (+ `pgvector` para búsqueda semántica en memoria/curación) | Dominio + checkpoints + vectores en un solo sistema |
| Cola / eventos | Redis + `arq` (o Celery) | Tareas largas: render, TTS, subida |
| Almacenamiento | S3 (MinIO en local) | Artefactos binarios y versionado |
| Slides | Marp (Markdown → HTML/PDF/PPTX) como formato canónico; export opcional a PPTX vía `python-pptx` | Las slides generadas por LLM en Markdown son revisables, diffables y evaluables |
| TTS | ElevenLabs u OpenAI TTS (interfaz `TTSProvider` intercambiable) | Calidad de voz; abstracción para no casarse con un proveedor |
| Vídeo | ffmpeg (composición slides+audio) en MVP; Remotion como mejora para animaciones | ffmpeg es suficiente para "slide + narración + capítulos" |
| Publicación | YouTube Data API v3 (OAuth del usuario) | Título, descripción, capítulos, miniatura, playlist |
| Observabilidad | LangSmith (trazas de agentes) + OpenTelemetry en API | Depuración de agentes y demo de ingeniería |
| Evaluación | LLM-as-judge con rúbricas + LangSmith evals | Ver sección 8 |
| Infra | Docker Compose (dev), contenedores en despliegue (Fly.io/Railway/K8s según necesidad) | Simplicidad primero |

---

## 5. Modelo de dominio

Entidades principales (tablas Postgres):

- **User**: auth, preferencias, credenciales OAuth (YouTube) cifradas.
- **Project** (proyecto educativo): tema, audiencia, nivel de profundidad, idioma, estilo, formato de salida deseado, estado.
- **AgentDefinition**: catálogo de tipos de agente (curador, diseñador, etc.) — código, herramientas permitidas, esquema de entrada/salida.
- **AgentProfile**: perfil guardable y reutilizable de un agente = `soul.md` + `agents.md` + configuración (modelo, temperatura, herramientas activadas). Un agente puede tener N perfiles ("Curador académico", "Curador divulgativo"...). Versionado.
- **Workflow**: definición declarativa del grafo (nodos = agente+perfil, aristas = flujo de artefactos, puntos de pausa/aprobación). Plantillas predefinidas ("Curso completo", "Solo slides", "Guion desde slides") + workflows personalizados del usuario.
- **Run**: ejecución de un workflow sobre un proyecto. Estado por nodo, checkpoints LangGraph, coste/tokens, logs.
- **Artifact**: salida versionada de un nodo (tipo, formato, URI S3, metadatos, hash, procedencia: qué run/nodo/perfil lo generó). Puede también ser **subido por el usuario** (entrada externa al pipeline).
- **Evaluation**: resultado de un evaluador sobre un artefacto (rúbrica, puntuación, feedback, veredicto pasar/revisar).
- **MemoryEntry / WikiPage**: páginas de la wiki de memoria por proyecto y por usuario (sección 7).

Contratos de artefactos (esquemas Pydantic + JSON Schema) — la clave de la modularidad:

| Tipo | Formato canónico |
|------|------------------|
| `research_brief` | Markdown estructurado + fuentes citadas |
| `course_plan` | JSON (módulos → lecciones/vídeos, objetivos de aprendizaje, duraciones) |
| `lesson_content` | Markdown por lección |
| `slide_deck` | Marp Markdown (+ HTML/PDF/PPTX renderizados) |
| `teaching_script` | Markdown alineado slide-a-slide (bloques por diapositiva) |
| `voice_script` | SSML/texto segmentado con marcas de tiempo estimadas |
| `narration_audio` | MP3/WAV por segmento + manifest JSON |
| `video` | MP4 + manifest de capítulos |
| `publication_package` | JSON: título, descripción, tags, capítulos, miniatura PNG, enlaces |

Cualquier agente declara qué tipos consume y produce; el editor de workflows solo permite conectar tipos compatibles, y el usuario puede aportar cualquier artefacto manualmente como punto de entrada.

---

## 6. Los agentes

Cada agente es un deep agent con: system prompt compuesto (base del rol + `soul.md` + `agents.md` del perfil activo), herramientas propias, acceso de lectura/escritura a su espacio de memoria, y contrato de entrada/salida.

1. **Curador de contenido** — herramientas: búsqueda web, fetch de URLs, búsqueda semántica sobre documentos subidos por el usuario, ejecución de código (verificar snippets). Produce `research_brief` con fuentes citadas y evaluación de fiabilidad.
2. **Diseñador de curso** — consume el brief + parámetros del proyecto; produce `course_plan` (módulos, lecciones/vídeos, objetivos, prerequisitos, duración estimada).
3. **Generador de lecciones** — produce `lesson_content` por lección; herramienta de ejecución de código en sandbox para validar ejemplos; consulta la wiki del proyecto para mantener coherencia terminológica entre lecciones.
4. **Diseñador de slides** — `lesson_content` → `slide_deck` (Marp). Herramientas: render/preview, generación de diagramas (Mermaid), generación de imágenes opcional. Criterios en su soul: densidad por slide, jerarquía visual, consistencia de tema.
5. **Guionista docente** — slides (+ lección) → `teaching_script`: amplía lo que aparece en pantalla como un profesor humano (ejemplos, analogías, transiciones, énfasis). Funciona también con slides subidas por el usuario (parseo de PPTX/PDF a estructura por slide).
6. **Adaptador de voz** — `teaching_script` → `voice_script`: reescribe para oralidad (frases cortas, sin referencias visuales tipo "como veis aquí"), segmenta por slide, añade pausas/SSML.
7. **Productor de vídeo** — orquesta TTS por segmento, renderiza slides a imágenes/vídeo, compone con ffmpeg (audio + slide sincronizados, intro/outro), genera capítulos a partir del manifest. Es el agente más "herramienta-céntrico": poca generación, mucha coordinación con verificación (duraciones, sincronía).
8. **Publicador YouTube** — produce `publication_package` (título optimizado, descripción con enlaces y capítulos, tags, miniatura generada) y, tras aprobación humana obligatoria (guardarraíl), sube vía YouTube API.
9. **Evaluadores** (transversales, sección 8) — no producen artefactos de curso sino `Evaluation`s que condicionan las transiciones del grafo.

---

## 7. Configuración de agentes: `soul.md`, `agents.md` y perfiles

- **`soul.md`** — personalidad y criterio: tono, estilo de comunicación, cómo toma decisiones, qué prioriza (p. ej. "prefiere rigor a exhaustividad; ante ambigüedad, elige el ejemplo más simple que sea correcto").
- **`agents.md`** — instrucciones operativas: convenciones de formato, reglas del dominio, restricciones, definición de "hecho" para su tarea.
- Composición del system prompt final: `prompt base del rol (código) + agents.md + soul.md`, en ese orden, con el prompt base marcando límites que el perfil no puede anular (guardarraíl de prompt).
- **Perfiles guardables**: CRUD completo en la UI con editor Markdown, versionado, duplicar-y-modificar, y perfiles de ejemplo incluidos de fábrica. Un workflow referencia agente+perfil por nodo, así el mismo pipeline puede correr en modo "académico" o "divulgativo" cambiando perfiles.
- Los perfiles se almacenan en Postgres (fuente de verdad) y se materializan como ficheros en el workspace del agente al ejecutar (coherente con el modelo de ficheros de deep agents).

### Memoria

Tres niveles, todos sobre el modelo filesystem-backed de deep agents:

1. **Memoria de ejecución** (efímera): workspace de ficheros del run — notas de planificación, borradores, TODOs del propio agente.
2. **Memoria de proyecto** (persistente): wiki estilo **OpenWiki Brains** — el sistema mantiene proactivamente páginas de wiki por proyecto (decisiones tomadas, glosario del curso, estilo acordado, feedback del usuario, fuentes curadas). Los agentes la leen para coherencia entre lecciones y la actualizan al terminar sus tareas. Backend: ficheros Markdown en S3 indexados con pgvector para búsqueda.
3. **Memoria de usuario** (persistente, transversal a proyectos): preferencias ("siempre en español", "slides oscuras", "voz X"), aprendidas de las correcciones del usuario y editables desde la UI.

Integración: se usa `deepagents` con un `BackendStore` propio (S3+Postgres) y un sub-agente "bibliotecario" que consolida notas de ejecución en la wiki de proyecto al cierre de cada nodo (patrón OpenWiki Brains de construcción proactiva de memoria).

---

## 8. Evaluación y guardarraíles

**Evaluadores automáticos** (LLM-as-judge con rúbricas explícitas versionadas), ejecutados como nodos de evaluación entre fases:

- **Calidad técnica**: exactitud de afirmaciones y código (el código se ejecuta en sandbox, no solo se juzga).
- **Claridad pedagógica**: alineación con objetivos de aprendizaje, progresión de dificultad, adecuación a la audiencia declarada.
- **Coherencia visual**: densidad de slides, consistencia de formato, legibilidad.
- **Adecuación de contenido**: idioma correcto, nivel correcto, sin contenido fuera de alcance.

**Mecánica en el grafo**: cada evaluación devuelve `pass` / `revise` (con feedback accionable) / `escalate` (humano). `revise` reenvía el artefacto al agente productor con el feedback (máx. N iteraciones, configurable); `escalate` dispara un interrupt de LangGraph y la UI pide decisión al usuario.

**Guardarraíles**:
- Publicación en YouTube **siempre** requiere aprobación humana explícita.
- Presupuesto por run (tokens/€) con corte y aviso.
- Límites de herramientas por agente (allowlist declarada en `AgentDefinition`, no ampliable por perfil).
- Sandbox para ejecución de código (contenedor sin red o con red restringida).
- Moderación de contenido de entrada/salida en los puntos de frontera (tema del proyecto, artefactos subidos por usuario).
- Trazabilidad completa: todo artefacto conserva procedencia (run, nodo, perfil, versión de prompt).

**Evals de desarrollo** (además de las de runtime): dataset de proyectos de prueba + regresión en LangSmith para detectar degradaciones al cambiar prompts/modelos.

---

## 9. API y frontend

### API (borrador de endpoints principales)

```
POST   /projects                        # crear proyecto (tema, audiencia, nivel, idioma, estilo, formato)
GET    /projects/{id}
POST   /projects/{id}/artifacts         # subir artefacto externo (p.ej. slides propias)
GET    /agents                          # catálogo de agentes y sus contratos
GET    /agents/{type}/profiles          # perfiles guardados
POST   /agents/{type}/profiles          # crear perfil (soul.md, agents.md, config)
GET    /workflows /workflows/{id}       # plantillas + workflows propios
POST   /workflows                       # crear/editar definición de grafo
POST   /projects/{id}/runs              # lanzar run (workflow + overrides)
GET    /runs/{id}                       # estado por nodo, coste, artefactos
GET    /runs/{id}/events                # SSE: progreso, tokens, evaluaciones
POST   /runs/{id}/resume                # reanudar tras interrupt (aprobación/feedback humano)
POST   /runs/{id}/cancel
GET    /artifacts/{id} /artifacts/{id}/download
GET/PUT /projects/{id}/wiki             # memoria de proyecto visible y editable
```

### Frontend (pantallas principales)

1. **Dashboard**: proyectos, estado de runs, costes.
2. **Nuevo proyecto**: formulario guiado (tema, audiencia, nivel, idioma, estilo, formato de salida) + selección de workflow (plantilla o propio).
3. **Editor de workflows**: React Flow — arrastrar agentes, conectar por tipos de artefacto compatibles, asignar perfil por nodo, marcar puntos de pausa/aprobación, guardar como plantilla.
4. **Panel de ejecución**: grafo en vivo con estado por nodo, stream de actividad del agente, evaluaciones con puntuaciones, botones aprobar/pedir cambios/parar aquí.
5. **Biblioteca de perfiles**: editor Markdown de `soul.md`/`agents.md` con preview, versiones, duplicar.
6. **Visor de artefactos**: preview por tipo (Markdown, slides renderizadas, reproductor audio/vídeo, diff entre versiones).
7. **Wiki del proyecto**: memoria navegable y editable.
8. **Ajustes**: claves de proveedor, OAuth YouTube, preferencias de usuario.

---

## 10. Roadmap detallado

### Fase 0 — Fundaciones (≈1 semana)
- Monorepo: `apps/web` (Next.js), `apps/api` (FastAPI), `packages/agents` (Python), `infra/` (Docker Compose: Postgres+pgvector, Redis, MinIO).
- CI (lint, typecheck, tests), pre-commit, esqueleto de auth (email o GitHub OAuth).
- Migraciones iniciales (User, Project) y CRUD de proyectos end-to-end.

### Fase 1 — Núcleo agentico (≈2 semanas)
- Runtime de agentes sobre `deepagents`: carga de `AgentDefinition`, composición de prompt con `soul.md`/`agents.md`, allowlist de herramientas, workspace de ficheros por run.
- CRUD + UI de perfiles con editor Markdown y versionado; perfiles de ejemplo.
- Worker (arq) + SSE de eventos hacia la UI.
- **Hito demo:** ejecutar el agente Curador de forma aislada desde la web y ver el `research_brief` con fuentes en el visor de artefactos.

### Fase 2 — Pipeline de contenido (≈2-3 semanas)
- Sistema de artefactos versionados (S3 + metadatos + contratos Pydantic) y subida de artefactos externos.
- Agentes Diseñador de curso, Generador de lecciones (con sandbox de código) y Diseñador de slides (Marp + render HTML/PDF/PPTX).
- Encadenado fijo Curador → Plan → Lecciones → Slides (grafo LangGraph hardcodeado, aún sin editor).
- **Hito demo:** de una idea a un deck de slides descargable por lección.

### Fase 3 — Orquestación editable (≈2-3 semanas)
- Formato declarativo de workflow (JSON) → compilador a grafo LangGraph dinámico; checkpointer Postgres; interrupts para aprobación humana; reanudación y cancelación.
- Editor visual React Flow con validación de compatibilidad de artefactos; plantillas ("Curso completo", "Solo slides", "Guion desde slides existentes").
- Panel de ejecución en vivo (estado por nodo, aprobar/revisar/parar).
- **Hito demo:** el usuario edita un workflow, lo lanza, lo pausa tras las slides y lo reanuda otro día.

### Fase 4 — Multimodal (≈3 semanas)
- Guionista docente (incl. parseo de PPTX/PDF subidos) y Adaptador de voz (SSML, segmentación).
- Integración TTS (interfaz `TTSProvider`, primer proveedor + caché de segmentos para no regenerar audio sin cambios).
- Productor de vídeo: render slides→frames, composición ffmpeg audio+vídeo, capítulos; pipeline en workers con progreso.
- **Hito demo:** vídeo MP4 completo de una lección con narración sincronizada.

### Fase 5 — Publicación y memoria avanzada (≈2 semanas)
- OAuth YouTube, agente Publicador (metadatos, miniatura, capítulos) con aprobación humana obligatoria.
- Wiki de memoria de proyecto (patrón OpenWiki Brains): sub-agente bibliotecario, indexación pgvector, UI de wiki; memoria de usuario transversal.
- **Hito demo:** flujo completo idea→vídeo publicado en YouTube; el proyecto siguiente reutiliza preferencias aprendidas.

### Fase 6 — Calidad y producción (≈2 semanas, parcialmente en paralelo desde la fase 2)
- Los 4 evaluadores como nodos de grafo con ciclo revise/escalate; rúbricas versionadas.
- Guardarraíles: presupuestos, moderación, sandbox endurecido.
- LangSmith en todo el runtime + dataset de regresión; hardening (rate limits, secretos, backups) y despliegue.
- **Hito demo:** run completo donde una evaluación rechaza un artefacto, el agente lo corrige y el usuario ve el ciclo en la UI.

**Total estimado: ~13-16 semanas** para una persona a tiempo completo (las fases 4-6 tienen solapes aprovechables).

---

## 11. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Coste de LLM en runs completos | Alto | Presupuesto por run, caché de artefactos (no regenerar lo no cambiado), modelos pequeños para tareas mecánicas, tokens visibles en UI |
| Calidad inconsistente entre lecciones | Alto | Wiki de proyecto (glosario/estilo compartido) + evaluador de coherencia + ciclo revise |
| Complejidad del editor de grafos | Medio | Empezar con plantillas fijas (fase 2) y sólo después el editor (fase 3); validación por tipos de artefacto limita errores |
| Sincronización audio/slides frágil | Medio | Manifest de tiempos por segmento generado por el TTS (no estimado); tests de composición con ffprobe |
| Dependencia de un proveedor (TTS/LLM) | Medio | Interfaces `TTSProvider`/`init_chat_model`; configuración de modelo por agente |
| Cuotas/verificación de YouTube API | Medio | Modo "paquete de publicación descargable" como fallback si la subida directa no está disponible |
| `deepagents`/OpenWiki evolucionan rápido | Medio | Fijar versiones, capa fina propia sobre sus APIs, tests de contrato |
| Prompt injection vía contenido curado de la web | Medio | Separar contenido no confiable en los prompts, allowlist de herramientas, evaluador de adecuación antes de avanzar de fase |

---

## 12. Estructura de repositorio propuesta

```
Learning-AI-Factory/
├── apps/
│   ├── web/                    # Next.js (UI)
│   └── api/                    # FastAPI (REST + SSE, workers arq)
├── packages/
│   └── factory_agents/         # Python: agentes, herramientas, grafos, evals
│       ├── agents/             # un módulo por agente (curator, planner, ...)
│       ├── tools/              # búsqueda, sandbox, slides, tts, video, youtube
│       ├── orchestration/      # compilador workflow JSON → LangGraph
│       ├── memory/             # backends deep agents + wiki (OpenWiki pattern)
│       ├── evals/              # rúbricas y jueces
│       └── contracts/          # esquemas Pydantic de artefactos
├── profiles/                   # perfiles de ejemplo (soul.md / agents.md)
├── workflows/                  # plantillas de workflow (JSON)
├── infra/                      # docker-compose, migraciones, despliegue
└── docs/                       # este plan, ADRs, guías
```

---

## 13. Primeros pasos concretos (siguiente sesión de trabajo)

1. Scaffolding del monorepo y Docker Compose (Fase 0).
2. Definir los contratos Pydantic de los 9 tipos de artefacto (son la columna vertebral de la modularidad — conviene fijarlos pronto).
3. Prototipo mínimo del runtime: un deep agent Curador con perfil `soul.md`/`agents.md` cargado desde fichero, corriendo por CLI antes de tener UI.
4. ADR-001: formato declarativo de workflows (JSON schema del grafo).
