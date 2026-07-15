"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type AgentProfile,
  type Artifact,
  type Job,
  type JobEvent,
  type Workflow,
} from "@/lib/api";
import {
  ConfirmDialog,
  ErrorBanner,
  IconBrain,
  IconCheck,
  IconFileText,
  IconCaptions,
  IconFlask,
  IconHand,
  IconImage,
  IconListTree,
  IconMic,
  IconPackage,
  IconMessage,
  IconPlay,
  IconSearch,
  IconPresentation,
  IconSparkles,
  IconTrendingUp,
  IconTrash,
  IconUpload,
  IconVideo,
  IconWrench,
  IconX,
  Spinner,
} from "@/components/ui";

const STATUS_BADGE: Record<Job["status"], { label: string; className: string }> = {
  queued: { label: "En cola", className: "badge-neutral" },
  running: { label: "Ejecutando", className: "badge-info" },
  waiting_approval: { label: "Esperando tu aprobación", className: "badge-warning" },
  done: { label: "Completado", className: "badge-success" },
  failed: { label: "Fallido", className: "badge-danger" },
};

const KIND_LABELS: Record<string, string> = {
  curator_run: "Curador de contenido",
  planner_run: "Diseñador del curso",
  lessons_run: "Generador de lecciones",
  slides_run: "Diseñador de slides",
  script_run: "Guionista docente",
  voice_run: "Adaptador a voz",
  video_run: "Montaje de vídeo",
  publisher_run: "Preparación de publicación",
  youtube_upload: "Subida a YouTube",
  analyst_run: "Análisis de rendimiento",
  pipeline_run: "Pipeline de contenido",
  workflow_run: "Workflow",
};

const STAGES: {
  agent: string;
  label: string;
  description: string;
  produces: string;
  consumes: string[];
}[] = [
  {
    agent: "curator",
    label: "Curador",
    description: "Investiga el tema y produce un brief documentado",
    produces: "research_brief",
    consumes: [],
  },
  {
    agent: "planner",
    label: "Plan del curso",
    description: "Estructura el curso en módulos y lecciones",
    produces: "course_plan",
    consumes: ["research_brief"],
  },
  {
    agent: "lessons",
    label: "Lecciones",
    description: "Redacta el contenido completo de cada lección",
    produces: "lesson_content",
    consumes: ["research_brief", "course_plan"],
  },
  {
    agent: "slides",
    label: "Slides",
    description: "Convierte cada lección en diapositivas",
    produces: "slide_deck",
    consumes: ["course_plan", "lesson_content"],
  },
  {
    agent: "script",
    label: "Guion docente",
    description: "Escribe el guion palabra a palabra por lección",
    produces: "teaching_script",
    consumes: ["slide_deck"],
  },
  {
    agent: "voice",
    label: "Adaptación a voz",
    description: "Adapta el guion a narración por segmentos",
    produces: "voice_script",
    consumes: ["teaching_script"],
  },
  {
    agent: "video",
    label: "Vídeo",
    description: "Sintetiza la voz y monta el vídeo (TTS + ffmpeg)",
    produces: "video",
    consumes: ["voice_script", "slide_deck"],
  },
  {
    agent: "publisher",
    label: "Publicación",
    description: "Prepara título, descripción, capítulos y miniatura",
    produces: "publication_package",
    consumes: ["video"],
  },
];

// Video production is tool-driven (TTS + ffmpeg), not an LLM agent with profiles.
const PROFILE_AGENTS = [
  "curator",
  "planner",
  "lessons",
  "slides",
  "script",
  "voice",
  "publisher",
];

const TYPE_LABELS: Record<string, string> = {
  research_brief: "Research brief",
  performance_report: "Informe de rendimiento",
  course_plan: "Plan del curso",
  lesson_content: "Lección",
  slide_deck: "Slides",
  teaching_script: "Guion docente",
  voice_script: "Guion de voz",
  video: "Vídeo",
  subtitles: "Subtítulos",
  publication_package: "Publicación",
  thumbnail: "Miniatura",
};

const UPLOAD_TYPES = [
  "research_brief",
  "course_plan",
  "lesson_content",
  "slide_deck",
  "teaching_script",
];

const EVENT_META: Record<
  string,
  { label: string; icon: typeof IconWrench; className: string }
> = {
  stage: { label: "Etapa", icon: IconPlay, className: "text-indigo-300" },
  tool_call: { label: "Herramienta", icon: IconWrench, className: "text-sky-300" },
  artifact: { label: "Artefacto", icon: IconFileText, className: "text-emerald-300" },
  evaluation: { label: "Evaluación", icon: IconFlask, className: "text-violet-300" },
  memory: { label: "Memoria", icon: IconBrain, className: "text-fuchsia-300" },
  approval_required: { label: "Aprobación", icon: IconHand, className: "text-amber-300" },
};

function formatElapsed(fromIso: string, toMs: number): string {
  const seconds = Math.max(0, Math.floor((toMs - new Date(fromIso).getTime()) / 1000));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m >= 60) return `${Math.floor(m / 60)} h ${m % 60} min`;
  return `${m}:${String(s).padStart(2, "0")} min`;
}

function EventLine({
  event,
  artifactHref,
}: {
  event: JobEvent;
  artifactHref?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = EVENT_META[event.type] ?? {
    label: "Mensaje",
    icon: IconMessage,
    className: "text-zinc-400",
  };
  const EventIcon = meta.icon;
  const isLong = event.summary.length > 260;
  const summary =
    isLong && !expanded
      ? `${event.summary.slice(0, 260).trimEnd()}…`
      : event.summary;
  return (
    <li className="animate-in flex items-start gap-3 px-4 py-2 text-sm">
      <span className={`mt-0.5 shrink-0 ${meta.className}`}>
        <EventIcon size={14} />
      </span>
      <span className="min-w-0 flex-1 break-words whitespace-pre-wrap leading-relaxed text-zinc-300">
        {summary}
        {isLong && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="ml-2 text-xs font-medium text-indigo-300 hover:underline"
          >
            {expanded ? "Ver menos" : "Leer completo"}
          </button>
        )}
        {artifactHref && (
          <Link
            href={artifactHref}
            className="ml-2 text-xs font-medium text-indigo-300 hover:underline"
          >
            Ver artefacto →
          </Link>
        )}
      </span>
      <span className="mt-0.5 shrink-0 text-[11px] tabular-nums text-zinc-600">
        {new Date(event.created_at).toLocaleTimeString("es", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })}
      </span>
    </li>
  );
}

function artifactIcon(type: string) {
  if (type === "course_plan") return <IconListTree size={16} />;
  if (type === "lesson_content") return <IconBrain size={16} />;
  if (type === "slide_deck") return <IconPresentation size={16} />;
  if (type === "teaching_script") return <IconMessage size={16} />;
  if (type === "voice_script") return <IconMic size={16} />;
  if (type === "video") return <IconVideo size={16} />;
  if (type === "subtitles") return <IconCaptions size={16} />;
  if (type === "publication_package") return <IconPackage size={16} />;
  if (type === "thumbnail") return <IconImage size={16} />;
  if (type === "research_brief") return <IconSearch size={16} />;
  if (type === "performance_report") return <IconTrendingUp size={16} />;
  return <IconFileText size={16} />;
}

const ACTIVE_STATUSES: Job["status"][] = ["queued", "running", "waiting_approval"];

export default function FactoryPanel({ projectId }: { projectId: string }) {
  const [profilesByAgent, setProfilesByAgent] = useState<
    Record<string, AgentProfile[]>
  >({});
  const [selectedProfile, setSelectedProfile] = useState<Record<string, string>>(
    {},
  );
  const [runs, setRuns] = useState<Job[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [activeRun, setActiveRun] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowId, setWorkflowId] = useState<string>("");
  const [feedback, setFeedback] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadType, setUploadType] = useState("slide_deck");
  const [artifactToDelete, setArtifactToDelete] = useState<Artifact | null>(
    null,
  );
  const [deletingArtifact, setDeletingArtifact] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [showHistory, setShowHistory] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const [artifactFilter, setArtifactFilter] = useState("all");
  const fileRef = useRef<HTMLInputElement>(null);
  const eventsEndRef = useRef<HTMLLIElement>(null);

  const refresh = useCallback(async () => {
    const [runList, artifactList] = await Promise.all([
      api.listProjectRuns(projectId),
      api.listProjectArtifacts(projectId),
    ]);
    setRuns(runList);
    setArtifacts(artifactList);
    return runList;
  }, [projectId]);

  const follow = useCallback(
    (job: Job) => {
      setActiveRun(job);
      setEvents(job.events ?? []);
      setError(null);
      sourceRef.current?.close();
      if (job.status === "done" || job.status === "failed") {
        api.getRun(job.id).then((full) => {
          setActiveRun(full);
          setEvents(full.events);
        });
        return;
      }
      const source = new EventSource(`/api/runs/${job.id}/events`);
      sourceRef.current = source;
      source.onmessage = (e) => {
        const event = JSON.parse(e.data) as JobEvent;
        setEvents((prev) =>
          prev.some((p) => p.seq === event.seq) ? prev : [...prev, event],
        );
      };
      source.addEventListener("done", async () => {
        source.close();
        const full = await api.getRun(job.id);
        setActiveRun(full);
        setEvents(full.events);
        await refresh();
      });
      source.onerror = () => source.close();
    },
    [refresh],
  );

  useEffect(() => {
    Promise.all(
      PROFILE_AGENTS.map(
        async (agent) => [agent, await api.listProfiles(agent)] as const,
      ),
    )
      .then((entries) => {
        setProfilesByAgent(Object.fromEntries(entries));
        setSelectedProfile(
          Object.fromEntries(
            entries.map(([agent, list]) => [
              agent,
              list.find((p) => p.is_default)?.id ?? "",
            ]),
          ),
        );
      })
      .catch(() => {});
    api
      .listWorkflows()
      .then((list) => {
        setWorkflows(list);
        if (list.length > 0) setWorkflowId(list[0].id);
      })
      .catch(() => {});
    // Resume the most recent unfinished run automatically, so a page reload
    // never hides a running job or a pending approval.
    refresh()
      .then((runList) => {
        const active = runList.find((r) => ACTIVE_STATUSES.includes(r.status));
        if (active) follow(active);
      })
      .catch(() => {});
    return () => sourceRef.current?.close();
  }, [projectId, refresh, follow]);

  const running =
    activeRun?.status === "queued" || activeRun?.status === "running";

  // Elapsed-time ticker while a run is live.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  // Keep the newest activity in view.
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events.length]);

  async function start(agent: string) {
    setError(null);
    try {
      const job = await api.createAgentRun(
        projectId,
        agent,
        selectedProfile[agent] || undefined,
      );
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo lanzar");
    }
  }

  async function startAnalytics() {
    setError(null);
    try {
      const job = await api.createAnalyticsRun(projectId);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo lanzar");
    }
  }

  async function startWorkflow() {
    if (!workflowId) return;
    setError(null);
    try {
      const job = await api.createWorkflowRun(projectId, workflowId);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo lanzar");
    }
  }

  async function decide(approved: boolean) {
    if (!activeRun) return;
    setDeciding(true);
    setError(null);
    try {
      const job = await api.approveRun(activeRun.id, approved, feedback);
      setFeedback("");
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo enviar");
    } finally {
      setDeciding(false);
    }
  }

  async function cancel() {
    if (!activeRun) return;
    setCancelling(true);
    setError(null);
    try {
      const job = await api.cancelRun(activeRun.id);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar");
    } finally {
      setCancelling(false);
    }
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      await api.uploadArtifact(projectId, file, uploadType);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo subir");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function chooseArtifact(artifactId: string) {
    setError(null);
    try {
      await api.selectArtifact(artifactId);
      await refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo cambiar la versión",
      );
    }
  }

  async function removeArtifact() {
    if (!artifactToDelete) return;
    setDeletingArtifact(true);
    setError(null);
    try {
      await api.deleteArtifact(artifactToDelete.id);
      setArtifactToDelete(null);
      await refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo eliminar el artefacto",
      );
    } finally {
      setDeletingArtifact(false);
    }
  }

  const artifactTypes = new Set(artifacts.map((a) => a.type));
  const selectedWorkflow = workflows.find(
    (workflow) => workflow.id === workflowId,
  );
  const workflowAgents = new Set(
    selectedWorkflow?.steps.map((step) => step.agent) ?? [],
  );
  const workflowMissing = (() => {
    const available = new Set(artifactTypes);
    const missing = new Set<string>();
    for (const step of selectedWorkflow?.steps ?? []) {
      const stage = STAGES.find((item) => item.agent === step.agent);
      for (const input of stage?.consumes ?? []) {
        if (!available.has(input)) missing.add(input);
      }
      if (stage) available.add(stage.produces);
    }
    return [...missing];
  })();
  const nextWorkflowAgent = selectedWorkflow?.steps.find((step) => {
      const stage = STAGES.find((item) => item.agent === step.agent);
      return stage ? !artifactTypes.has(stage.produces) : false;
    })?.agent;
  const activeWorkflowAgent =
    activeRun?.kind === "workflow_run" &&
    (running || activeRun.status === "waiting_approval")
      ? [...events].reverse().find((event) => event.data?.agent)?.data?.agent ??
        nextWorkflowAgent
      : nextWorkflowAgent;
  const doneCount = STAGES.filter((s) => artifactTypes.has(s.produces)).length;
  const lastEvent = events.length > 0 ? events[events.length - 1] : null;
  const artifactFilterOptions = [...artifactTypes].sort((a, b) =>
    (TYPE_LABELS[a] ?? a).localeCompare(TYPE_LABELS[b] ?? b, "es"),
  );
  const filteredArtifacts =
    artifactFilter === "all"
      ? artifacts
      : artifacts.filter((artifact) => artifact.type === artifactFilter);

  const canCancel =
    activeRun?.status === "queued" || activeRun?.status === "waiting_approval";
  const statusBadge = activeRun ? STATUS_BADGE[activeRun.status] : null;

  return (
    <section className="mt-10">
      {/* ------ Header + workflow launcher ------ */}
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-zinc-50">
            Línea de producción
          </h2>
          <p className="mt-0.5 text-sm text-zinc-400">
            Lanza un workflow completo o ejecuta etapas sueltas.{" "}
            <span className="text-zinc-500">
              {doneCount}/{STAGES.length} etapas con resultado
            </span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
            disabled={running}
            className="input max-w-56 py-2 text-sm"
            aria-label="Workflow a ejecutar"
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <button
            onClick={startWorkflow}
            disabled={running || !workflowId || workflowMissing.length > 0}
            title={
              workflowMissing.length > 0
                ? `Faltan artefactos previos: ${workflowMissing
                    .map((type) => TYPE_LABELS[type] ?? type)
                    .join(", ")}`
                : undefined
            }
            className="btn-primary"
          >
            <IconPlay size={14} />
            Ejecutar workflow
          </button>
          <button
            onClick={startAnalytics}
            disabled={running}
            title="Analiza métricas y comentarios de los vídeos publicados de este proyecto"
            className="btn-secondary"
          >
            <IconTrendingUp size={15} />
            Analizar rendimiento
          </button>
        </div>
      </div>

      {/* ------ Pipeline stages ------ */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((stage, i) => {
          const done = artifactTypes.has(stage.produces);
          const profiles = profilesByAgent[stage.agent] ?? [];
          const missingInputs = stage.consumes.filter(
            (type) => !artifactTypes.has(type),
          );
          const inWorkflow = workflowAgents.has(stage.agent);
          const isCurrentWorkflowStep =
            inWorkflow && stage.agent === activeWorkflowAgent;
          return (
            <div
              key={stage.agent}
              className={`card flex flex-col p-4 transition-colors ${
                isCurrentWorkflowStep
                  ? "stage-workflow-current"
                  : inWorkflow
                    ? "stage-workflow"
                    : done
                      ? "border-emerald-400/20"
                      : ""
              }`}
            >
              <div className="mb-1.5 flex items-center gap-2.5">
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                    done
                      ? "bg-emerald-400/15 text-emerald-300"
                      : "bg-white/[0.06] text-zinc-400"
                  }`}
                >
                  {done ? <IconCheck size={13} /> : i + 1}
                </span>
                <span className="min-w-0 truncate text-sm font-semibold text-zinc-100">
                  {stage.label}
                </span>
              </div>
              <p className="mb-3 flex-1 text-xs leading-relaxed text-zinc-500">
                {stage.description}
              </p>
              <div className="flex items-center gap-2">
                {profiles.length > 0 ? (
                  <select
                    value={selectedProfile[stage.agent] ?? ""}
                    onChange={(e) =>
                      setSelectedProfile((prev) => ({
                        ...prev,
                        [stage.agent]: e.target.value,
                      }))
                    }
                    className="input min-w-0 flex-1 px-2 py-1.5 text-xs"
                    aria-label={`Perfil para ${stage.label}`}
                  >
                    {profiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} (v{p.version})
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="flex-1 self-center text-[11px] text-zinc-600">
                    Automático (TTS + ffmpeg)
                  </span>
                )}
                <button
                  onClick={() => start(stage.agent)}
                  disabled={running || missingInputs.length > 0}
                  className="btn-secondary btn-sm shrink-0"
                  title={
                    missingInputs.length > 0
                      ? `Antes necesitas: ${missingInputs
                          .map((type) => TYPE_LABELS[type] ?? type)
                          .join(", ")}`
                      : `Ejecutar ${stage.label}`
                  }
                >
                  <IconPlay size={12} />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      {/* ------ Live run monitor ------ */}
      {activeRun && statusBadge && (
        <div className="card animate-in mb-6 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-white/[0.06] bg-white/[0.02] px-4 py-3">
            {running ? <span className="dot-live" /> : null}
            <span className="text-sm font-semibold text-zinc-100">
              {KIND_LABELS[activeRun.kind] ?? activeRun.kind}
            </span>
            <span className={statusBadge.className}>{statusBadge.label}</span>
            {activeRun.started_at && (
              <span className="text-xs tabular-nums text-zinc-500">
                {formatElapsed(
                  activeRun.started_at,
                  activeRun.finished_at
                    ? new Date(activeRun.finished_at).getTime()
                    : now,
                )}
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              {canCancel && (
                <button
                  onClick={cancel}
                  disabled={cancelling}
                  className="btn-danger btn-sm"
                >
                  {cancelling ? "Cancelando…" : "Cancelar"}
                </button>
              )}
              <button
                onClick={() => {
                  sourceRef.current?.close();
                  setActiveRun(null);
                }}
                className="btn-ghost btn-sm"
                aria-label="Cerrar monitor"
              >
                <IconX size={14} />
              </button>
            </div>
          </div>

          {/* Current activity strip */}
          {running && (
            <div className="flex items-center gap-3 border-b border-indigo-400/15 bg-indigo-500/[0.07] px-4 py-2.5">
              <Spinner />
              <p className="min-w-0 flex-1 truncate text-sm text-indigo-200">
                {lastEvent
                  ? lastEvent.summary
                  : "Arrancando el agente, preparando contexto…"}
              </p>
            </div>
          )}

          {activeRun.status === "failed" && (
            <div className="border-b border-red-400/15 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
              {activeRun.error}
            </div>
          )}

          {activeRun.status === "waiting_approval" && (
            <div className="border-b-2 border-indigo-400/30 bg-[#fbf6ea] px-4 py-4">
              <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#241d18]">
                <IconHand size={16} />
                El workflow está en pausa esperando tu revisión. Comprueba el
                último artefacto generado y decide.
              </p>
              <input
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Feedback opcional (obligatorio si rechazas)"
                className="input mb-3"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => decide(true)}
                  disabled={deciding}
                  className="btn-success"
                >
                  <IconCheck size={15} />
                  Aprobar y continuar
                </button>
                <button
                  onClick={() => decide(false)}
                  disabled={deciding || !feedback.trim()}
                  title={
                    feedback.trim()
                      ? undefined
                      : "Escribe feedback para poder rechazar"
                  }
                  className="btn-danger"
                >
                  <IconX size={15} />
                  Rechazar con feedback
                </button>
              </div>
            </div>
          )}

          <ul className="max-h-72 divide-y divide-white/[0.04] overflow-y-auto py-1">
            {events.map((e) => (
              <EventLine
                key={e.seq}
                event={e}
                artifactHref={
                  e.data?.artifact_id ? `/artifacts/${e.data.artifact_id}` : undefined
                }
              />
            ))}
            {events.length === 0 && (
              <li className="px-4 py-3 text-sm text-zinc-500">
                Sin actividad todavía…
              </li>
            )}
            <li ref={eventsEndRef} aria-hidden />
          </ul>
        </div>
      )}

      {/* ------ Run history ------ */}
      {runs.length > 0 && (
        <div className="mb-8">
          <button
            onClick={() => setShowHistory((v) => !v)}
            className="btn-ghost btn-sm -ml-2"
          >
            {showHistory ? "Ocultar historial" : `Historial de ejecuciones (${runs.length})`}
          </button>
          {showHistory && (
            <ul className="animate-in mt-2 space-y-1.5">
              {runs.map((r) => {
                const badge = STATUS_BADGE[r.status];
                return (
                  <li key={r.id}>
                    <button
                      onClick={() => follow(r)}
                      className={`card card-hover flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm ${
                        activeRun?.id === r.id ? "border-indigo-400/40" : ""
                      }`}
                    >
                      <span className="min-w-0 flex-1 truncate font-medium text-zinc-200">
                        {KIND_LABELS[r.kind] ?? r.kind}
                      </span>
                      <span className="shrink-0 text-xs text-zinc-500">
                        {new Date(r.created_at).toLocaleString("es")}
                      </span>
                      <span className={`${badge.className} shrink-0`}>
                        {badge.label}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* ------ Artifacts ------ */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold tracking-tight text-zinc-100">
          Artefactos
          {artifacts.length > 0 && (
            <span className="ml-2 text-sm font-normal text-zinc-500">
              {filteredArtifacts.length === artifacts.length
                ? artifacts.length
                : `${filteredArtifacts.length} de ${artifacts.length}`}
            </span>
          )}
        </h3>
        <div className="flex items-center gap-2">
          <select
            value={artifactFilter}
            onChange={(e) => setArtifactFilter(e.target.value)}
            className="input w-auto px-2 py-1.5 text-xs"
            aria-label="Filtrar artefactos por tipo"
          >
            <option value="all">Todos los tipos</option>
            {artifactFilterOptions.map((type) => (
              <option key={type} value={type}>
                {TYPE_LABELS[type] ?? type}
              </option>
            ))}
          </select>
          <select
            value={uploadType}
            onChange={(e) => setUploadType(e.target.value)}
            className="input w-auto px-2 py-1.5 text-xs"
            aria-label="Tipo del artefacto a subir"
          >
            {UPLOAD_TYPES.map((type) => (
              <option key={type} value={type}>
                {TYPE_LABELS[type]}
              </option>
            ))}
          </select>
          <label className="btn-secondary btn-sm cursor-pointer">
            <IconUpload size={13} />
            {uploading ? "Subiendo…" : "Subir propio"}
            <input
              ref={fileRef}
              type="file"
              accept=".md,.json,.txt,.pptx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
              }}
            />
          </label>
        </div>
      </div>
      {artifacts.length === 0 ? (
        <div className="card border-dashed p-8 text-center">
          <p className="flex items-center justify-center gap-2 text-sm text-zinc-400">
            <IconSparkles size={15} className="text-indigo-300" />
            Todavía no hay artefactos: ejecuta el Curador o sube material propio.
          </p>
        </div>
      ) : filteredArtifacts.length === 0 ? (
        <div className="card border-dashed p-6 text-center text-sm text-zinc-500">
          No hay artefactos del tipo seleccionado.
        </div>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {filteredArtifacts.map((a) => (
            <li key={a.id}>
              <div className="card card-hover flex items-center gap-2 px-3 py-3 text-sm">
                <Link
                  href={`/artifacts/${a.id}`}
                  className="flex min-w-0 flex-1 items-center gap-3"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-zinc-300 bg-[#f4ead7] text-indigo-500">
                    {artifactIcon(a.type)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-zinc-200">
                      {a.title || a.type}
                    </span>
                    <span className="block text-xs text-zinc-500">
                      {TYPE_LABELS[a.type] ?? a.type} ·{" "}
                      {new Date(a.created_at).toLocaleString("es")}
                    </span>
                  </span>
                </Link>
                <select
                  value={a.id}
                  onChange={(event) => chooseArtifact(event.target.value)}
                  className="input max-w-32 shrink-0 px-2 py-1.5 text-xs"
                  aria-label={`Versión activa de ${a.title || a.type}`}
                  title="La versión elegida será la que consuman los siguientes agentes"
                >
                  {a.versions.map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version}
                      {version.is_selected ? " · activa" : ""}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => setArtifactToDelete(a)}
                  className="btn-ghost btn-sm shrink-0 text-red-300 hover:text-red-200"
                  aria-label={`Eliminar versión ${a.version} de ${a.title || a.type}`}
                  title={`Eliminar la versión activa v${a.version}`}
                >
                  <IconTrash size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={artifactToDelete !== null}
        title="Eliminar versión del artefacto"
        description={
          artifactToDelete
            ? `Se eliminará la versión v${artifactToDelete.version} de «${artifactToDelete.title || artifactToDelete.type}». ${
                artifactToDelete.versions.length > 1
                  ? "Se activará automáticamente la versión más reciente restante."
                  : "Es la única versión, por lo que desaparecerá la tarjeta."
              }`
            : ""
        }
        busy={deletingArtifact}
        onCancel={() => setArtifactToDelete(null)}
        onConfirm={removeArtifact}
      />
    </section>
  );
}
