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
| 1 | Ideación asistida | Agente de Ideación: convierte una idea vaga en un brief estructurado mediante conversación y preguntas de opción múltiple (runtime agentico mínimo) |
| 2 | Núcleo agentico | Runtime de agentes completo (deep agents), sistema `soul.md`/`agents.md` + perfiles, agente Curador end-to-end |
| 3 | Pipeline de contenido | Agentes Diseñador de curso, Generador de lecciones y Slides; artefactos versionados |
| 4 | Orquestación de workflows | Motor LangGraph con grafos editables, pausa/reanudación, human-in-the-loop, editor visual |
| 5 | Multimodal | Guion docente, adaptación a voz, TTS, montaje de vídeo (ffmpeg/Remotion) |
| 6 | Publicación y memoria avanzada | Agente Publicador YouTube, OpenWiki Brains como memoria de proyecto/usuario |
| 7 | Calidad y producción | Evaluadores automáticos, guardarraíles, observabilidad (LangSmith), despliegue |
| 8 | Mejora continua | Agente Analista: métricas y comentarios de YouTube → recomendaciones a la memoria principal y propuestas de cambio en los `agents.md` de cada agente (feedback loop automático) |

Cada fase termina con algo demostrable en la web app. El detalle está en la sección 10.

---

## 3. Arquitectura general

**Despliegue local: exactamente 2 contenedores Docker** (requisito de diseño). Uno para el frontend (Next.js) y uno para el backend (FastAPI + orquestador + workers in-process). Sin Postgres, sin Redis, sin MinIO: SQLite y el sistema de ficheros locales cubren todo, montados en volúmenes para persistencia.

```
┌────────────────────────────────────────────────────────────┐
│  Contenedor 1 — Frontend (Next.js)                         │
│  - Proyectos, chat de ideación, editor de workflows        │
│    (React Flow), editor de perfiles soul.md/agents.md,     │
│    visor de artefactos, panel de ejecución en tiempo real  │
└──────────────┬─────────────────────────────────────────────┘
               │ REST + SSE
┌──────────────▼─────────────────────────────────────────────┐
│  Contenedor 2 — Backend (FastAPI, Python)                  │
│                                                            │
│  API: auth, CRUD proyectos/workflows/perfiles,             │
│       lanzamiento y control de ejecuciones, SSE            │
│                                                            │
│  Orquestador LangGraph (in-process):                       │
│   - grafo por workflow, interrupts (HITL)                  │
│   - checkpointer SQLite (langgraph-checkpoint-sqlite)      │
│                                                            │
│  Workers in-process (asyncio task runner + cola en         │
│  SQLite): ejecución de agentes, TTS, render vídeo,         │
│  subida YouTube — con ffmpeg instalado en la imagen        │
│                                                            │
│  Volúmenes montados:                                       │
│   - /data/db/factory.sqlite   (dominio + checkpoints +     │
│     vectores vía sqlite-vec)                               │
│   - /data/artifacts/          (md, pptx/html, mp3, mp4,    │
│     png — artefactos versionados)                          │
│   - /data/memory/             (workspaces de agentes +     │
│     wiki de proyecto estilo OpenWiki Brains)               │
└────────────────────────────────────────────────────────────┘
```

**Decisiones clave:**

- **Backend en Python** (FastAPI): el ecosistema deep agents / LangGraph es Python-first; TTS, ffmpeg y evaluación también.
- **SQLite como única base de datos**: dominio (vía SQLAlchemy, que deja abierta una migración futura a Postgres si hiciera falta multi-usuario a escala), checkpoints de LangGraph (`langgraph-checkpoint-sqlite`) y búsqueda vectorial (`sqlite-vec`) en un único fichero con WAL activado. SQLite es monoescritor: todas las escrituras pasan por el proceso backend, lo cual encaja con el diseño de workers in-process.
- **Ejecuciones largas fuera del ciclo request/response pero dentro del mismo contenedor**: un task runner asyncio con cola persistida en SQLite (los jobs sobreviven reinicios) ejecuta workflows y tareas pesadas; la API solo lanza, consulta estado y retransmite eventos vía SSE desde un pub/sub in-process.
- **LangGraph como motor de workflows**: los grafos se construyen dinámicamente a partir de una definición declarativa (JSON) editable desde la UI. El checkpointer SQLite da pausa/reanudación, reintentos y time-travel gratis.
- **Cada agente = subgrafo/nodo `deepagents`**: con sus herramientas, su memoria (backend de ficheros) y su configuración de personalidad inyectada como system prompt desde `soul.md` + `agents.md`.
- **Artefactos como ciudadanos de primera clase**: toda salida (outline, lección, slides, guion, audio, vídeo) es un artefacto versionado en el volumen `/data/artifacts` con metadatos en SQLite, detrás de una interfaz `ArtifactStore` (implementación local ahora; S3 sería un adaptador futuro sin tocar el resto). Esto permite entrar al pipeline por cualquier punto (p. ej. subir slides propias y generar solo el guion).

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
| Base de datos | SQLite (WAL) vía SQLAlchemy + `langgraph-checkpoint-sqlite` + `sqlite-vec` para vectores | Dominio + checkpoints + búsqueda semántica en un solo fichero; cero servicios externos; SQLAlchemy deja abierta la puerta a Postgres |
| Cola / eventos | Task runner asyncio in-process con cola persistida en SQLite; pub/sub in-process para SSE | Tareas largas (render, TTS, subida) sin Redis; los jobs sobreviven reinicios del contenedor |
| Almacenamiento | Sistema de ficheros local (`/data/artifacts`, volumen Docker) tras interfaz `ArtifactStore` | Artefactos binarios y versionado sin MinIO; adaptador S3 posible a futuro |
| Slides | Marp (Markdown → HTML/PDF/PPTX) como formato canónico; export opcional a PPTX vía `python-pptx` | Las slides generadas por LLM en Markdown son revisables, diffables y evaluables |
| TTS | ElevenLabs u OpenAI TTS (interfaz `TTSProvider` intercambiable) | Calidad de voz; abstracción para no casarse con un proveedor |
| Vídeo | ffmpeg (composición slides+audio) en MVP; Remotion como mejora para animaciones | ffmpeg es suficiente para "slide + narración + capítulos" |
| Publicación | YouTube Data API v3 (OAuth del usuario) | Título, descripción, capítulos, miniatura, playlist |
| Analítica | YouTube Analytics API + YouTube Data API (comentarios) | Feedback loop del Analista de mejora continua (fase 8) |
| Observabilidad | LangSmith (trazas de agentes) + OpenTelemetry en API | Depuración de agentes y demo de ingeniería |
| Evaluación | LLM-as-judge con rúbricas + LangSmith evals | Ver sección 8 |
| Infra | Docker Compose con **exactamente 2 servicios**: `frontend` y `backend` (ffmpeg y Marp incluidos en la imagen del backend); volúmenes para `/data` | Requisito: levantar todo en local con un contenedor para el back y otro para el front |

---

## 5. Modelo de dominio

Entidades principales (tablas SQLite vía SQLAlchemy):

- **User**: auth, preferencias, credenciales OAuth (YouTube) cifradas.
- **Project** (proyecto educativo): tema, audiencia, nivel de profundidad, idioma, estilo, formato de salida deseado, estado. Puede nacer de una **IdeationSession** o crearse con parámetros manuales.
- **IdeationSession**: conversación con el Asistente de Ideación — historial de mensajes, preguntas estructuradas planteadas (con sus 3-4 opciones) y respuestas elegidas; termina materializando un `course_idea_brief` y opcionalmente un Project.
- **AgentDefinition**: catálogo de tipos de agente (curador, diseñador, etc.) — código, herramientas permitidas, esquema de entrada/salida.
- **AgentProfile**: perfil guardable y reutilizable de un agente = `soul.md` + `agents.md` + configuración (modelo, temperatura, herramientas activadas). Un agente puede tener N perfiles ("Curador académico", "Curador divulgativo"...). Versionado.
- **Workflow**: definición declarativa del grafo (nodos = agente+perfil, aristas = flujo de artefactos, puntos de pausa/aprobación). Plantillas predefinidas ("Curso completo", "Solo slides", "Guion desde slides") + workflows personalizados del usuario.
- **Run**: ejecución de un workflow sobre un proyecto. Estado por nodo, checkpoints LangGraph, coste/tokens, logs.
- **Artifact**: salida versionada de un nodo (tipo, formato, ruta en `/data/artifacts`, metadatos, hash, procedencia: qué run/nodo/perfil lo generó). Puede también ser **subido por el usuario** (entrada externa al pipeline).
- **Evaluation**: resultado de un evaluador sobre un artefacto (rúbrica, puntuación, feedback, veredicto pasar/revisar).
- **MemoryEntry / WikiPage**: páginas de la wiki de memoria por proyecto y por usuario (sección 7).
- **ImprovementProposal**: propuesta del Analista de mejora continua — tipo (actualización de wiki | diff sobre `agents.md` de un perfil), evidencia (métricas/comentarios que la justifican), estado (pendiente / aprobada / rechazada / aplicada) y, si se aplica, la nueva versión de perfil o página de wiki resultante.

Contratos de artefactos (esquemas Pydantic + JSON Schema) — la clave de la modularidad:

| Tipo | Formato canónico |
|------|------------------|
| `course_idea_brief` | JSON: tema afinado, audiencia, nivel, idioma, estilo, objetivos, alcance, ángulo diferencial, preguntas abiertas — salida del Asistente de Ideación y entrada del Curador |
| `research_brief` | Markdown estructurado + fuentes citadas |
| `course_plan` | JSON (módulos → lecciones/vídeos, objetivos de aprendizaje, duraciones) |
| `lesson_content` | Markdown por lección |
| `slide_deck` | Marp Markdown (+ HTML/PDF/PPTX renderizados) |
| `teaching_script` | Markdown alineado slide-a-slide (bloques por diapositiva) |
| `voice_script` | SSML/texto segmentado con marcas de tiempo estimadas |
| `audio` | MP3/WAV persistido por segmento + manifest JSON versionado con duraciones y hashes |
| `video` | MP4 + manifest de capítulos |
| `publication_package` | JSON: título, descripción, tags, capítulos, miniatura PNG, enlaces |
| `performance_report` | JSON + Markdown: métricas del vídeo/canal (retención, CTR, visualizaciones), análisis de comentarios (temas, sentimiento, preguntas frecuentes) |
| `improvement_proposal` | JSON: recomendaciones para la memoria principal (páginas de wiki a actualizar) y diffs propuestos sobre los `agents.md` de agentes concretos, con evidencia que los justifica |

Cualquier agente declara qué tipos consume y produce; el editor de workflows solo permite conectar tipos compatibles, y el usuario puede aportar cualquier artefacto manualmente como punto de entrada.

---

## 6. Los agentes

Cada agente es un deep agent con: system prompt compuesto (base del rol + `soul.md` + `agents.md` del perfil activo), herramientas propias, acceso de lectura/escritura a su espacio de memoria, y contrato de entrada/salida.

1. **Asistente de Ideación** — el primer agente del pipeline y el único puramente conversacional. El usuario le da una idea vaga ("algo de computación cuántica para gente técnica") y el agente la rebota con él: propone ángulos, detecta ambigüedades y hace **preguntas con 3-4 respuestas posibles** (más opción libre) para afinar audiencia, nivel, alcance, formato y objetivos. Herramientas: una herramienta estructurada `ask_user_question` (pregunta + opciones tipadas que la UI renderiza como botones), búsqueda web ligera para validar demanda/competencia del tema, y lectura de la memoria de usuario (preferencias de proyectos anteriores) para no volver a preguntar lo ya sabido. Produce `course_idea_brief`: la especificación afinada que se convierte en los parámetros del proyecto y en la entrada del Curador. El usuario puede saltarse este agente si ya tiene la idea clara.
2. **Curador de contenido** — herramientas: búsqueda web, fetch de URLs, búsqueda semántica sobre documentos subidos por el usuario, ejecución de código (verificar snippets). Consume el `course_idea_brief` (o los parámetros manuales del proyecto) y produce `research_brief` con fuentes citadas y evaluación de fiabilidad.
3. **Diseñador de curso** — consume el brief + parámetros del proyecto; produce `course_plan` (módulos, lecciones/vídeos, objetivos, prerequisitos, duración estimada).
4. **Generador de lecciones** — produce `lesson_content` por lección; herramienta de ejecución de código en sandbox para validar ejemplos; consulta la wiki del proyecto para mantener coherencia terminológica entre lecciones.
5. **Diseñador de slides** — `lesson_content` → `slide_deck` (Marp). Herramientas: render/preview, generación de diagramas (Mermaid), generación de imágenes opcional. Criterios en su soul: densidad por slide, jerarquía visual, consistencia de tema.
6. **Guionista docente** — slides (+ lección) → `teaching_script`: amplía lo que aparece en pantalla como un profesor humano (ejemplos, analogías, transiciones, énfasis). Funciona también con slides subidas por el usuario (parseo de PPTX/PDF a estructura por slide).
7. **Adaptador de voz** — `teaching_script` → `voice_script`: reescribe para oralidad (frases cortas, sin referencias visuales tipo "como veis aquí"), segmenta por slide, añade pausas/SSML.
8. **Generador de audio** — `voice_script` → `audio` + `subtitles`: sintetiza TTS por segmento, mide duraciones reales y publica copias versionadas y verificables para que puedan reutilizarse sin nuevas llamadas al proveedor.
9. **Montador de vídeo** — `slide_deck` + `audio` → `video`: etapa automática y determinista que renderiza slides y compone con ffmpeg usando orientación y modo de subtítulos del perfil. Remontar slides no regenera audio.
10. **Publicador YouTube** — produce `publication_package` (título optimizado, descripción con enlaces y capítulos, tags, miniatura generada) y, tras aprobación humana obligatoria (guardarraíl), sube vía YouTube API.
11. **Analista de mejora continua** — cierra el feedback loop. No corre dentro de un run de producción sino de forma periódica (programada) o bajo demanda. Herramientas: YouTube Analytics API (retención por minuto, CTR, visualizaciones, suscripciones atribuidas), YouTube Data API (comentarios), análisis de sentimiento y clustering de temas en comentarios. Produce `performance_report` por vídeo/canal y, a partir de patrones ("los vídeos con intros >40s pierden 20% de retención", "muchos comentarios piden más ejemplos de código"), genera `improvement_proposal`s de dos tipos: **(a)** actualizaciones a la memoria principal (páginas de wiki de usuario/canal: "qué funciona en este canal"), y **(b)** diffs concretos sobre los `agents.md` de agentes específicos (p. ej. añadir al `agents.md` del Guionista "limita la introducción a 30 segundos"). Ninguna propuesta se aplica sola: ver guardarraíles (sección 8) — se revisan como diffs en la UI y, al aprobarse, crean nuevas versiones de perfil, de modo que cada iteración de curso hereda lo aprendido.
12. **Evaluadores** (transversales, sección 8) — no producen artefactos de curso sino `Evaluation`s que condicionan las transiciones del grafo.

---

## 7. Configuración de agentes: `soul.md`, `agents.md` y perfiles

- **`soul.md`** — personalidad y criterio: tono, estilo de comunicación, cómo toma decisiones, qué prioriza (p. ej. "prefiere rigor a exhaustividad; ante ambigüedad, elige el ejemplo más simple que sea correcto").
- **`agents.md`** — instrucciones operativas: convenciones de formato, reglas del dominio, restricciones, definición de "hecho" para su tarea.
- Composición del system prompt final: `prompt base del rol (código) + agents.md + soul.md`, en ese orden, con el prompt base marcando límites que el perfil no puede anular (guardarraíl de prompt).
- **Perfiles guardables**: CRUD completo en la UI con editor Markdown, versionado, duplicar-y-modificar, y perfiles de ejemplo incluidos de fábrica. Un workflow referencia agente+perfil por nodo, así el mismo pipeline puede correr en modo "académico" o "divulgativo" cambiando perfiles.
- Los perfiles se almacenan en SQLite (fuente de verdad) y se materializan como ficheros en el workspace del agente al ejecutar (coherente con el modelo de ficheros de deep agents).
- **Los perfiles evolucionan con el feedback loop**: el Analista de mejora continua (sección 6, agente 10) propone diffs sobre los `agents.md`; al aprobarlos, se crea una nueva versión del perfil con procedencia (qué evidencia motivó el cambio), de modo que el historial de versiones cuenta la historia de aprendizaje del sistema.

### Memoria

Tres niveles, todos sobre el modelo filesystem-backed de deep agents:

1. **Memoria de ejecución** (efímera): workspace de ficheros del run — notas de planificación, borradores, TODOs del propio agente.
2. **Memoria de proyecto** (persistente): wiki estilo **OpenWiki Brains** — el sistema mantiene proactivamente páginas de wiki por proyecto (decisiones tomadas, glosario del curso, estilo acordado, feedback del usuario, fuentes curadas). Los agentes la leen para coherencia entre lecciones y la actualizan al terminar sus tareas. Backend: ficheros Markdown en `/data/memory` indexados con `sqlite-vec` para búsqueda semántica.
3. **Memoria de usuario/canal** (persistente, transversal a proyectos): preferencias ("siempre en español", "slides oscuras", "voz X"), aprendidas de las correcciones del usuario y editables desde la UI. Aquí escribe también el Analista de mejora continua sus hallazgos aprobados ("en este canal, las intros cortas retienen mejor"), de modo que la memoria principal mejora con cada vídeo publicado.

Integración: se usa `deepagents` con un `BackendStore` propio (filesystem local + SQLite) y un sub-agente "bibliotecario" que consolida notas de ejecución en la wiki de proyecto al cierre de cada nodo (patrón OpenWiki Brains de construcción proactiva de memoria).

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
- **Las propuestas del feedback loop nunca se auto-aplican**: los cambios a `agents.md` o a la memoria principal que propone el Analista de mejora continua se presentan como diffs revisables en la UI y requieren aprobación. Antes de proponerse, cada diff de `agents.md` pasa el dataset de regresión (evals de desarrollo) para comprobar que no degrada la calidad — un feedback loop sin esta válvula puede amplificar sesgos de métricas (optimizar CTR a costa de rigor).
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
POST   /ideation                        # iniciar sesión de ideación desde una idea vaga
POST   /ideation/{id}/messages          # turno de conversación; la respuesta puede incluir una
                                        #   pregunta estructurada con 3-4 opciones (la UI la
                                        #   renderiza como botones + campo libre)
POST   /ideation/{id}/finalize          # materializar course_idea_brief → crear Project
POST   /projects                        # crear proyecto manual (tema, audiencia, nivel, idioma, estilo, formato)
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
POST   /analytics/refresh               # lanzar análisis del Analista de mejora continua
GET    /analytics/reports               # performance_reports por vídeo/canal
GET    /improvements                    # propuestas pendientes (wiki y diffs de agents.md)
POST   /improvements/{id}/approve       # aplicar (nueva versión de perfil / página de wiki)
POST   /improvements/{id}/reject
```

### Frontend (pantallas principales)

1. **Dashboard**: proyectos, estado de runs, costes.
2. **Asistente de ideación**: chat con el Asistente de Ideación donde las preguntas estructuradas se renderizan como tarjetas con 3-4 opciones clicables (+ respuesta libre); panel lateral con el brief construyéndose en vivo; botón "crear proyecto desde este brief".
3. **Nuevo proyecto** (manual): formulario guiado (tema, audiencia, nivel, idioma, estilo, formato de salida) + selección de workflow (plantilla o propio) — para cuando el usuario ya tiene la idea clara y quiere saltarse la ideación.
4. **Editor de workflows**: React Flow — arrastrar agentes, conectar por tipos de artefacto compatibles, asignar perfil por nodo, marcar puntos de pausa/aprobación, guardar como plantilla.
5. **Panel de ejecución**: grafo en vivo con estado por nodo, stream de actividad del agente, evaluaciones con puntuaciones, botones aprobar/pedir cambios/parar aquí.
6. **Biblioteca de perfiles**: editor Markdown de `soul.md`/`agents.md` con preview, versiones, duplicar; en cada versión, enlace a la propuesta de mejora que la originó (si vino del feedback loop).
7. **Visor de artefactos**: preview por tipo (Markdown, slides renderizadas, reproductor audio/vídeo, diff entre versiones).
8. **Wiki del proyecto**: memoria navegable y editable.
9. **Panel de mejora continua**: métricas por vídeo (retención, CTR, comentarios analizados), lista de propuestas pendientes con diffs de `agents.md` y cambios de wiki, botones aprobar/rechazar con la evidencia al lado.
10. **Ajustes**: claves de proveedor, OAuth YouTube, preferencias de usuario.

---

## 10. Roadmap detallado

### Fase 0 — Fundaciones (≈1 semana)
- Monorepo: `apps/web` (Next.js), `apps/api` (FastAPI), `packages/agents` (Python), `infra/` (Docker Compose con **solo 2 servicios**: `frontend` y `backend`; volúmenes `/data` para SQLite, artefactos y memoria; ffmpeg y Marp en la imagen del backend).
- CI (lint, typecheck, tests), pre-commit, esqueleto de auth (email o GitHub OAuth).
- Migraciones iniciales SQLite/Alembic (User, Project) y CRUD de proyectos end-to-end.
- **Hito demo:** `docker compose up` levanta la plataforma completa con dos contenedores.

### Fase 1 — Ideación asistida (≈1-2 semanas)
- Runtime agentico mínimo (suficiente para un agente conversacional; el runtime completo llega en fase 2).
- Asistente de Ideación: chat con streaming + herramienta `ask_user_question` (preguntas estructuradas con 3-4 opciones que la UI renderiza como tarjetas clicables), búsqueda web ligera, panel de brief en vivo.
- Contrato `course_idea_brief` y materialización brief → Project.
- **Hito demo:** de "algo de cuántica para técnicos" a un proyecto creado con brief afinado en una conversación de 5 minutos.

### Fase 2 — Núcleo agentico (≈2 semanas)
- Runtime de agentes completo sobre `deepagents`: carga de `AgentDefinition`, composición de prompt con `soul.md`/`agents.md`, allowlist de herramientas, workspace de ficheros por run.
- CRUD + UI de perfiles con editor Markdown y versionado; perfiles de ejemplo (el Asistente de Ideación se migra a este sistema de perfiles).
- Task runner asyncio con cola persistida en SQLite + SSE de eventos hacia la UI.
- **Hito demo:** ejecutar el agente Curador de forma aislada desde la web (alimentado por un `course_idea_brief`) y ver el `research_brief` con fuentes en el visor de artefactos.

### Fase 3 — Pipeline de contenido (≈2-3 semanas)
- Sistema de artefactos versionados (`ArtifactStore` local + metadatos SQLite + contratos Pydantic) y subida de artefactos externos.
- Agentes Diseñador de curso, Generador de lecciones (con sandbox de código) y Diseñador de slides (Marp + render HTML/PDF/PPTX).
- Encadenado fijo Ideación → Curador → Plan → Lecciones → Slides (grafo LangGraph hardcodeado, aún sin editor).
- **Hito demo:** de una idea a un deck de slides descargable por lección.

### Fase 4 — Orquestación editable (≈2-3 semanas)
- Formato declarativo de workflow (JSON) → compilador a grafo LangGraph dinámico; checkpointer SQLite; interrupts para aprobación humana; reanudación y cancelación.
- Editor visual React Flow con validación de compatibilidad de artefactos; plantillas ("Curso completo", "Solo slides", "Guion desde slides existentes").
- Panel de ejecución en vivo (estado por nodo, aprobar/revisar/parar).
- **Hito demo:** el usuario edita un workflow, lo lanza, lo pausa tras las slides y lo reanuda otro día.

### Fase 5 — Multimodal (≈3 semanas)
- Guionista docente (incl. parseo de PPTX/PDF subidos) y Adaptador de voz (SSML, segmentación).
- Integración TTS (interfaz `TTSProvider`, primer proveedor + caché de segmentos para no regenerar audio sin cambios).
- Productor de vídeo: render slides→frames, composición ffmpeg audio+vídeo, capítulos; pipeline en el task runner con progreso.
- **Hito demo:** vídeo MP4 completo de una lección con narración sincronizada.

### Fase 6 — Publicación y memoria avanzada (≈2 semanas)
- OAuth YouTube, agente Publicador (metadatos, miniatura, capítulos) con aprobación humana obligatoria.
- Wiki de memoria de proyecto (patrón OpenWiki Brains): sub-agente bibliotecario, indexación `sqlite-vec`, UI de wiki; memoria de usuario/canal transversal.
- **Hito demo:** flujo completo idea→vídeo publicado en YouTube; el proyecto siguiente reutiliza preferencias aprendidas.

### Fase 7 — Calidad y producción (≈2 semanas, parcialmente en paralelo desde la fase 3)
- Los 4 evaluadores como nodos de grafo con ciclo revise/escalate; rúbricas versionadas.
- Guardarraíles: presupuestos, moderación, sandbox endurecido.
- LangSmith en todo el runtime + dataset de regresión; hardening (rate limits, secretos, backups del volumen `/data`) y despliegue.
- **Hito demo:** run completo donde una evaluación rechaza un artefacto, el agente lo corrige y el usuario ve el ciclo en la UI.

### Fase 8 — Mejora continua / feedback loop (≈2 semanas)
- Integración YouTube Analytics API + lectura de comentarios; ejecución programada (scheduler in-process) y bajo demanda del Analista de mejora continua.
- Generación de `performance_report`s (retención, CTR, análisis de sentimiento y temas en comentarios) y `improvement_proposal`s: actualizaciones a la memoria principal y diffs sobre los `agents.md` de agentes concretos.
- Panel de mejora continua: revisar evidencia, aprobar/rechazar diffs; al aprobar, nueva versión de perfil con procedencia. Validación previa de cada diff contra el dataset de regresión (fase 7).
- **Hito demo:** tras publicar 2-3 vídeos, el Analista propone "acorta las intros" como diff sobre el `agents.md` del Guionista; el usuario lo aprueba y el siguiente curso se genera ya con la mejora — el loop completo idea → vídeo → métricas → mejora → mejor vídeo.

**Total estimado: ~16-19 semanas** para una persona a tiempo completo (las fases 5-7 tienen solapes aprovechables).

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
| Prompt injection vía contenido curado de la web o comentarios de YouTube | Medio | Separar contenido no confiable en los prompts, allowlist de herramientas, evaluador de adecuación antes de avanzar de fase; los comentarios que procesa el Analista son entrada no confiable y nunca se convierten en instrucciones directas, solo en propuestas revisables |
| El feedback loop optimiza métricas equivocadas (CTR a costa de rigor) | Alto | Ninguna propuesta se auto-aplica: aprobación humana + validación contra dataset de regresión antes de proponer; procedencia completa de cada cambio de perfil para poder revertir |
| Límites de SQLite (monoescritor, concurrencia) | Bajo-Medio | WAL + todas las escrituras en el proceso backend (diseño in-process); SQLAlchemy permite migrar a Postgres si algún día hay multi-usuario a escala |

---

## 12. Estructura de repositorio propuesta

```
Learning-AI-Factory/
├── apps/
│   ├── web/                    # Next.js (UI)
│   └── api/                    # FastAPI (REST + SSE, task runner in-process)
├── packages/
│   └── factory_agents/         # Python: agentes, herramientas, grafos, evals
│       ├── agents/             # un módulo por agente (ideation, curator, planner,
│       │                       #   ..., publisher, analyst)
│       ├── tools/              # búsqueda, sandbox, slides, tts, video, youtube,
│       │                       #   youtube_analytics, ask_user_question
│       ├── orchestration/      # compilador workflow JSON → LangGraph + task runner
│       ├── memory/             # backends deep agents + wiki (OpenWiki pattern)
│       ├── evals/              # rúbricas y jueces
│       └── contracts/          # esquemas Pydantic de artefactos
├── profiles/                   # perfiles de ejemplo (soul.md / agents.md)
├── workflows/                  # plantillas de workflow (JSON)
├── infra/                      # docker-compose (2 servicios: frontend, backend),
│                               #   Dockerfiles, migraciones Alembic
├── data/                       # volumen local (gitignored): factory.sqlite,
│                               #   artifacts/, memory/
└── docs/                       # este plan, ADRs, guías
```

---

## 13. Primeros pasos concretos (siguiente sesión de trabajo)

1. Scaffolding del monorepo y Docker Compose con los 2 contenedores (frontend, backend) y volúmenes `/data` (Fase 0).
2. Definir los contratos Pydantic de los 12 tipos de artefacto (son la columna vertebral de la modularidad — conviene fijarlos pronto), empezando por `course_idea_brief`.
3. Prototipo mínimo del Asistente de Ideación: agente conversacional con la herramienta `ask_user_question` (3-4 opciones), corriendo por CLI antes de tener UI, con perfil `soul.md`/`agents.md` cargado desde fichero.
4. ADR-001: formato declarativo de workflows (JSON schema del grafo). ADR-002: esquema de la cola de jobs en SQLite.
