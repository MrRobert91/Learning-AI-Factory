"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type AgentProfile,
  type Artifact,
  type CourseVideoPreflight,
  type CourseVideoTransition,
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
  IconPause,
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
import {
  AGENT_INPUTS,
  AGENT_NAMES,
  AGENT_OUTPUTS,
  contextualArtifactActions,
  WORKFLOW_AGENTS,
  type ContextualArtifactAction,
  type WorkflowAgent,
} from "@/lib/workflowRules";

const STATUS_BADGE: Record<Job["status"], { label: string; className: string }> = {
  queued: { label: "En cola", className: "badge-neutral" },
  running: { label: "Ejecutando", className: "badge-info" },
  pausing: { label: "Pausando…", className: "badge-warning" },
  paused: { label: "Pausado", className: "badge-warning" },
  waiting_approval: { label: "Esperando tu aprobación", className: "badge-warning" },
  canceling: { label: "Cancelando…", className: "badge-danger" },
  canceled: { label: "Cancelado", className: "badge-neutral" },
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
  course_video_export: "Vídeo completo del curso",
  publisher_run: "Preparación de publicación",
  youtube_upload: "Subida a YouTube",
  analyst_run: "Análisis de rendimiento",
  pipeline_run: "Pipeline de contenido",
  workflow_run: "Workflow",
};

const STAGES: {
  agent: WorkflowAgent;
  label: string;
  description: string;
  produces: string;
  consumes: string[];
}[] = [
  {
    agent: "curator",
    label: "Curador",
    description: "Investiga el tema y produce un brief documentado",
    produces: AGENT_OUTPUTS.curator[0],
    consumes: AGENT_INPUTS.curator,
  },
  {
    agent: "planner",
    label: "Plan del curso",
    description: "Estructura el curso en módulos y lecciones",
    produces: AGENT_OUTPUTS.planner[0],
    consumes: AGENT_INPUTS.planner,
  },
  {
    agent: "lessons",
    label: "Lecciones",
    description: "Redacta el contenido completo de cada lección",
    produces: AGENT_OUTPUTS.lessons[0],
    consumes: AGENT_INPUTS.lessons,
  },
  {
    agent: "slides",
    label: "Slides",
    description: "Convierte cada lección en diapositivas",
    produces: AGENT_OUTPUTS.slides[0],
    consumes: AGENT_INPUTS.slides,
  },
  {
    agent: "script",
    label: "Guion docente",
    description: "Escribe el guion palabra a palabra por lección",
    produces: AGENT_OUTPUTS.script[0],
    consumes: AGENT_INPUTS.script,
  },
  {
    agent: "voice",
    label: "Adaptación a voz",
    description: "Adapta el guion a narración por segmentos",
    produces: AGENT_OUTPUTS.voice[0],
    consumes: AGENT_INPUTS.voice,
  },
  {
    agent: "video",
    label: "Vídeo",
    description: "Sintetiza la voz y monta el vídeo (TTS + ffmpeg)",
    produces: AGENT_OUTPUTS.video[0],
    consumes: AGENT_INPUTS.video,
  },
  {
    agent: "publisher",
    label: "Publicación",
    description: "Prepara título, descripción, capítulos y miniatura",
    produces: AGENT_OUTPUTS.publisher[0],
    consumes: AGENT_INPUTS.publisher,
  },
];

const PROFILE_AGENTS = WORKFLOW_AGENTS;

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
  course_video: "Vídeo completo",
  course_subtitles: "Subtítulos del curso",
  course_video_manifest: "Capítulos del curso",
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
  if (type === "video" || type === "course_video") return <IconVideo size={16} />;
  if (type === "subtitles" || type === "course_subtitles") {
    return <IconCaptions size={16} />;
  }
  if (type === "publication_package") return <IconPackage size={16} />;
  if (type === "thumbnail") return <IconImage size={16} />;
  if (type === "research_brief") return <IconSearch size={16} />;
  if (type === "performance_report") return <IconTrendingUp size={16} />;
  return <IconFileText size={16} />;
}

function orientationLabel(metadata: Record<string, unknown>): string | null {
  return metadata.orientation === "vertical"
    ? "Vertical 9:16"
    : metadata.orientation === "horizontal"
      ? "Horizontal 16:9"
      : null;
}

function durationLabel(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function paletteLabel(metadata: Record<string, unknown>): string | null {
  const labels: Record<string, string> = {
    factory: "Factory",
    neutral_light: "neutra clara",
    dark: "oscura",
    high_contrast: "de alto contraste",
    warm: "cálida",
    custom: "personalizada",
  };
  return typeof metadata.palette_name === "string"
    ? `paleta ${labels[metadata.palette_name] ?? metadata.palette_name}`
    : null;
}

const ACTIVE_STATUSES: Job["status"][] = [
  "queued",
  "running",
  "pausing",
  "paused",
  "waiting_approval",
  "canceling",
];

type PendingArtifactAction =
  | {
      kind: "agent";
      action: ContextualArtifactAction;
      sourceArtifactId: string;
      requestId: string;
    }
  | {
      kind: "course_video";
      sourceArtifactId: string;
      requestId: string;
    };

function selectedArtifactIdsByType(
  artifacts: Artifact[],
): Record<string, string[]> {
  const selected: Record<string, string[]> = {};
  for (const artifact of artifacts) {
    (selected[artifact.type] ??= []).push(artifact.id);
  }
  return selected;
}

function artifactActionLabel(action: ContextualArtifactAction): string {
  return `${action.regenerates ? "Regenerar" : "Continuar con"} ${
    AGENT_NAMES[action.agent]
  }`;
}

export default function FactoryPanel({
  projectId,
  durationConfigured = true,
  selectedWorkflowId = null,
  onSelectedWorkflowChange,
}: {
  projectId: string;
  durationConfigured?: boolean;
  selectedWorkflowId?: string | null;
  onSelectedWorkflowChange?: (workflowId: string) => void;
}) {
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
  const [workflowPreferenceState, setWorkflowPreferenceState] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [failedWorkflowId, setFailedWorkflowId] = useState<string | null>(null);
  const [workflowFallbackWarning, setWorkflowFallbackWarning] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [exportingSlidesPptx, setExportingSlidesPptx] = useState(false);
  const [uploadType, setUploadType] = useState("slide_deck");
  const [showUpload, setShowUpload] = useState(false);
  const [artifactToDelete, setArtifactToDelete] = useState<Artifact | null>(
    null,
  );
  const [deletingArtifact, setDeletingArtifact] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [showHistory, setShowHistory] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const [artifactFilter, setArtifactFilter] = useState("all");
  const [courseVideoPreflight, setCourseVideoPreflight] =
    useState<CourseVideoPreflight | null>(null);
  const [courseVideoSubtitles, setCourseVideoSubtitles] = useState<
    boolean | null
  >(null);
  const [courseVideoChapters, setCourseVideoChapters] = useState(true);
  const [courseVideoTransition, setCourseVideoTransition] =
    useState<CourseVideoTransition>("none");
  const [loadingCourseVideoPreflight, setLoadingCourseVideoPreflight] =
    useState(false);
  const [startingCourseVideo, setStartingCourseVideo] = useState(false);
  const [pendingArtifactAction, setPendingArtifactAction] =
    useState<PendingArtifactAction | null>(null);
  const [startingArtifactAction, setStartingArtifactAction] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const eventsEndRef = useRef<HTMLLIElement>(null);
  const launchLocksRef = useRef(new Set<string>());

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
      if (
        job.status === "done" ||
        job.status === "failed" ||
        job.status === "canceled"
      ) {
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

  useEffect(() => {
    let canceled = false;
    api
      .listWorkflows()
      .then((list) => {
        if (canceled) return;
        setWorkflows(list);
        const stored = selectedWorkflowId
          ? list.find((workflow) => workflow.id === selectedWorkflowId)
          : undefined;
        setWorkflowId(stored?.id ?? list[0]?.id ?? "");
        setWorkflowFallbackWarning(Boolean(selectedWorkflowId && !stored));
      })
      .catch(() => {
        if (!canceled) {
          setError("No se pudieron cargar los workflows disponibles");
        }
      });
    return () => {
      canceled = true;
    };
  }, [projectId, selectedWorkflowId]);

  useEffect(() => {
    setWorkflowPreferenceState("idle");
    setFailedWorkflowId(null);
  }, [projectId]);

  useEffect(() => {
    if (!artifacts.some((artifact) => artifact.type === "course_plan")) {
      setCourseVideoPreflight(null);
      return;
    }
    let canceled = false;
    setLoadingCourseVideoPreflight(true);
    api
      .getCourseVideoPreflight(projectId, {
        ...(courseVideoSubtitles === null
          ? {}
          : { include_subtitles: courseVideoSubtitles }),
        include_chapters: courseVideoChapters,
        transition: courseVideoTransition,
      })
      .then((preflight) => {
        if (canceled) return;
        setCourseVideoPreflight(preflight);
        if (courseVideoSubtitles === null) {
          setCourseVideoSubtitles(preflight.include_subtitles);
        }
      })
      .catch((err) => {
        if (!canceled) {
          setError(
            err instanceof Error
              ? err.message
              : "No se pudo ejecutar el preflight del vídeo completo",
          );
        }
      })
      .finally(() => {
        if (!canceled) setLoadingCourseVideoPreflight(false);
      });
    return () => {
      canceled = true;
    };
  }, [
    artifacts,
    courseVideoChapters,
    courseVideoSubtitles,
    courseVideoTransition,
    projectId,
  ]);

  const running =
    activeRun?.status === "queued" ||
    activeRun?.status === "running" ||
    activeRun?.status === "pausing" ||
    activeRun?.status === "canceling";
  const launchBlocked =
    activeRun !== null && ACTIVE_STATUSES.includes(activeRun.status);

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

  async function start(
    agent: WorkflowAgent,
    trigger: "stage_card" | "artifact_card" = "stage_card",
    requestId = crypto.randomUUID(),
  ): Promise<boolean> {
    const lockKey = `${trigger}:${agent}`;
    if (launchLocksRef.current.has(lockKey)) return false;
    launchLocksRef.current.add(lockKey);
    setError(null);
    try {
      const job = await api.createAgentRun(
        projectId,
        agent,
        selectedProfile[agent] || undefined,
        {
          expected_input_artifact_ids: selectedArtifactIdsByType(artifacts),
          request_id: requestId,
          trigger,
        },
      );
      await refresh();
      follow(job);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo lanzar");
      return false;
    } finally {
      launchLocksRef.current.delete(lockKey);
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

  async function startCourseVideo(requestId?: string): Promise<boolean> {
    if (courseVideoSubtitles === null) return false;
    const lockKey = "course-video";
    if (launchLocksRef.current.has(lockKey)) return false;
    launchLocksRef.current.add(lockKey);
    setStartingCourseVideo(true);
    setError(null);
    try {
      const job = await api.createCourseVideo(projectId, {
        include_subtitles: courseVideoSubtitles,
        include_chapters: courseVideoChapters,
        transition: courseVideoTransition,
        request_id: requestId,
      });
      await refresh();
      follow(job);
      return true;
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo generar el vídeo completo",
      );
      return false;
    } finally {
      launchLocksRef.current.delete(lockKey);
      setStartingCourseVideo(false);
    }
  }

  async function confirmArtifactAction() {
    if (!pendingArtifactAction) return;
    setStartingArtifactAction(true);
    const launched =
      pendingArtifactAction.kind === "agent"
        ? await start(
            pendingArtifactAction.action.agent,
            "artifact_card",
            pendingArtifactAction.requestId,
          )
        : await startCourseVideo(pendingArtifactAction.requestId);
    if (launched) setPendingArtifactAction(null);
    setStartingArtifactAction(false);
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

  async function saveWorkflowSelection(nextWorkflowId: string) {
    const previousWorkflowId = workflowId;
    setWorkflowId(nextWorkflowId);
    setWorkflowPreferenceState("saving");
    setFailedWorkflowId(null);
    setWorkflowFallbackWarning(false);
    try {
      const updated = await api.updateProject(projectId, {
        selected_workflow_id: nextWorkflowId,
      });
      setWorkflowPreferenceState("saved");
      onSelectedWorkflowChange?.(updated.selected_workflow_id ?? nextWorkflowId);
    } catch {
      setWorkflowId(previousWorkflowId);
      setWorkflowPreferenceState("error");
      setFailedWorkflowId(nextWorkflowId);
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
      setConfirmCancel(false);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar");
    } finally {
      setCancelling(false);
    }
  }

  async function pause() {
    if (!activeRun) return;
    setControlling(true);
    setError(null);
    try {
      const job = await api.pauseRun(activeRun.id);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo pausar");
    } finally {
      setControlling(false);
    }
  }

  async function resume() {
    if (!activeRun) return;
    setControlling(true);
    setError(null);
    try {
      const job = await api.resumeRun(activeRun.id);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo reanudar");
    } finally {
      setControlling(false);
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

  async function downloadSlidesPptx() {
    setExportingSlidesPptx(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/exports/slides.pptx`,
      );
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(
          payload?.detail ?? "No se pudo generar el PPTX de las slides",
        );
      }
      const url = URL.createObjectURL(await response.blob());
      const disposition = response.headers.get("content-disposition") ?? "";
      const encodedName = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1];
      const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
      const link = document.createElement("a");
      link.href = url;
      link.download = encodedName
        ? decodeURIComponent(encodedName)
        : (plainName ?? "slides.pptx");
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo generar el PPTX de las slides",
      );
    } finally {
      setExportingSlidesPptx(false);
    }
  }

  const artifactTypes = new Set(artifacts.map((a) => a.type));
  const selectedWorkflow = workflows.find(
    (workflow) => workflow.id === workflowId,
  );
  const workflowNeedsDuration =
    selectedWorkflow?.steps.some((step) => step.agent !== "curator") ?? false;
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
  let activeWorkflowAgent: string | undefined;
  if (
    activeRun?.kind === "workflow_run" &&
    (running || activeRun.status === "waiting_approval")
  ) {
    for (const event of events) {
      if (
        event.data?.status === "running" ||
        event.data?.status === "waiting_approval"
      ) {
        activeWorkflowAgent = event.data.agent;
      } else if (
        event.data?.status === "done" &&
        event.data.agent === activeWorkflowAgent
      ) {
        activeWorkflowAgent = undefined;
      }
    }
    if (running) activeWorkflowAgent ??= nextWorkflowAgent;
  }
  const directActiveAgent =
    (running || activeRun?.status === "waiting_approval") &&
    activeRun?.kind.endsWith("_run")
      ? activeRun.kind.replace(/_run$/, "")
      : undefined;
  const activeStageAgent =
    activeRun?.kind === "workflow_run" ? activeWorkflowAgent : directActiveAgent;
  const doneCount = STAGES.filter((stage) =>
    artifactTypes.has(stage.produces),
  ).length;
  const lastEvent = events.length > 0 ? events[events.length - 1] : null;
  const artifactFilterOptions = [...artifactTypes].sort((a, b) =>
    (TYPE_LABELS[a] ?? a).localeCompare(TYPE_LABELS[b] ?? b, "es"),
  );
  const filteredArtifacts =
    artifactFilter === "all"
      ? artifacts
      : artifacts.filter((artifact) => artifact.type === artifactFilter);
  const pendingAgent =
    pendingArtifactAction?.kind === "agent"
      ? pendingArtifactAction.action.agent
      : null;
  const pendingProfile = pendingAgent
    ? (profilesByAgent[pendingAgent] ?? []).find(
        (profile) =>
          profile.id === selectedProfile[pendingAgent] ||
          (!selectedProfile[pendingAgent] && profile.is_default),
      )
    : null;
  const pendingInputTypes =
    pendingArtifactAction?.kind === "agent"
      ? pendingArtifactAction.action.inputs
      : pendingArtifactAction?.kind === "course_video"
        ? ["course_plan", "video"]
        : [];
  const pendingInputArtifacts = artifacts.filter((artifact) =>
    pendingInputTypes.includes(artifact.type),
  );

  const canPause =
    activeRun?.status === "queued" ||
    activeRun?.status === "running" ||
    activeRun?.status === "waiting_approval";
  const canResume = activeRun?.status === "paused";
  const canCancel =
    activeRun !== null &&
    [
      "queued",
      "running",
      "pausing",
      "paused",
      "waiting_approval",
    ].includes(activeRun.status);
  const statusBadge = activeRun ? STATUS_BADGE[activeRun.status] : null;

  return (
    <section className="mt-10">
      {!durationConfigured && (
        <div className="mb-5 rounded-xl border border-amber-400/30 bg-amber-500/[0.07] p-4">
          <p className="text-sm font-semibold text-amber-200">
            Falta configurar la duración del curso
          </p>
          <p className="mt-1 text-sm text-amber-100/70">
            Puedes ejecutar el Curador, pero planner y las fases posteriores están
            bloqueadas hasta elegir módulos, vídeos y minutos por vídeo.
          </p>
        </div>
      )}
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
        <div className="flex flex-wrap items-start gap-2">
          <div className="flex flex-col items-end gap-1">
            <select
              value={workflowId}
              onChange={(event) =>
                void saveWorkflowSelection(event.target.value)
              }
              disabled={launchBlocked || workflowPreferenceState === "saving"}
              className="input max-w-56 py-2 text-sm"
              aria-label="Workflow a ejecutar"
            >
              {workflows.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            {workflowPreferenceState === "saving" && (
              <span className="text-xs text-zinc-500" role="status">
                Guardando selección…
              </span>
            )}
            {workflowPreferenceState === "saved" && (
              <span className="text-xs text-emerald-400" role="status">
                Selección guardada
              </span>
            )}
          </div>
          <button
            onClick={startWorkflow}
            disabled={
              launchBlocked ||
              !workflowId ||
              workflowMissing.length > 0 ||
              (!durationConfigured && workflowNeedsDuration)
            }
            title={
              !durationConfigured && workflowNeedsDuration
                ? "Configura antes la duración y estructura del proyecto"
                : workflowMissing.length > 0
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
            disabled={launchBlocked}
            title="Analiza métricas y comentarios de los vídeos publicados de este proyecto"
            className="btn-secondary"
          >
            <IconTrendingUp size={15} />
            Analizar rendimiento
          </button>
        </div>
      </div>
      {workflowFallbackWarning && (
        <div className="mb-4 rounded-xl border border-amber-400/30 bg-amber-500/[0.07] px-4 py-3">
          <p className="text-sm font-semibold text-amber-200">
            El workflow guardado ya no está disponible
          </p>
          <p className="mt-1 text-xs text-amber-100/70">
            Se muestra una opción temporal. Elige un workflow para confirmar una
            nueva selección.
          </p>
        </div>
      )}
      {workflowPreferenceState === "error" && failedWorkflowId && (
        <div
          className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-red-400/25 bg-red-500/[0.06] px-4 py-3"
          role="alert"
        >
          <p className="min-w-0 flex-1 text-sm text-red-300">
            No se pudo guardar el workflow. La selección anterior sigue activa.
          </p>
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => void saveWorkflowSelection(failedWorkflowId)}
          >
            Reintentar
          </button>
        </div>
      )}

      {/* ------ Pipeline stages ------ */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((stage, i) => {
          const isActive = stage.agent === activeStageAgent;
          const isWaiting =
            isActive && activeRun?.status === "waiting_approval";
          const done = !isActive && artifactTypes.has(stage.produces);
          const profiles = profilesByAgent[stage.agent] ?? [];
          const workflowStep = selectedWorkflow?.steps.find(
            (item) => item.agent === stage.agent,
          );
          const configuredProfileId = workflowStep
            ? workflowStep.profile_id ||
              profiles.find((profile) => profile.is_default)?.id ||
              profiles[0]?.id
            : selectedProfile[stage.agent];
          const configuredProfile = profiles.find(
            (profile) => profile.id === configuredProfileId,
          );
          const frozenPolicy = activeRun?.review_policies?.[stage.agent];
          const reviewEnabled =
            frozenPolicy?.enabled ??
            configuredProfile?.automatic_review_enabled ??
            false;
          const maxRegenerations =
            frozenPolicy?.max_regenerations ??
            configuredProfile?.max_automatic_regenerations ??
            0;
          const humanReviewEnabled =
            frozenPolicy?.human_review_enabled ??
            configuredProfile?.human_review_enabled ??
            false;
          const missingInputs = stage.consumes.filter(
            (type) => !artifactTypes.has(type),
          );
          const needsDuration =
            !durationConfigured && stage.agent !== "curator";
          const inWorkflow = workflowAgents.has(stage.agent);
          const isCurrentWorkflowStep = isActive;
          return (
            <div
              key={stage.agent}
              className={`card flex flex-col p-4 transition-colors ${
                isCurrentWorkflowStep
                  ? isWaiting
                    ? "border-amber-400/50 bg-amber-500/[0.06]"
                    : "stage-workflow-current"
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
                    isWaiting
                      ? "bg-amber-400/15 text-amber-300"
                      : isActive
                        ? "bg-indigo-400/15 text-indigo-300"
                      : done
                        ? "bg-emerald-400/15 text-emerald-300"
                        : "bg-white/[0.06] text-zinc-400"
                  }`}
                >
                  {isWaiting ? (
                    <IconHand size={13} />
                  ) : isActive ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : done ? (
                    <IconCheck size={13} />
                  ) : (
                    i + 1
                  )}
                </span>
                <span className="min-w-0 truncate text-sm font-semibold text-zinc-100">
                  {stage.label}
                </span>
                {isActive &&
                  (isWaiting ? (
                    <span className="badge-warning text-[10px]">En espera</span>
                  ) : (
                    <span className="badge-info text-[10px]">En curso</span>
                  ))}
              </div>
              <p className="mb-3 flex-1 text-xs leading-relaxed text-zinc-500">
                {stage.description}
              </p>
              <p className="mb-2 text-[11px] text-zinc-500">
                Revisión automática: {reviewEnabled ? `sí · ${maxRegenerations} regeneraciones` : "no"}
                {frozenPolicy ? " · política congelada del run" : ""}
              </p>
              <p className="mb-2 text-[11px] text-zinc-500">
                Aprobación humana: {humanReviewEnabled ? "sí" : "no"}
                {frozenPolicy ? " · política congelada del run" : ""}
              </p>
              {stage.agent === "voice" && configuredProfile?.tts_model && (
                <p className="mb-2 text-[11px] text-zinc-500">
                  TTS: {configuredProfile.tts_provider} · {configuredProfile.tts_model}
                  {" · "}
                  {configuredProfile.tts_language === "inherit"
                    ? "idioma del proyecto"
                    : configuredProfile.tts_language}
                  {" · "}
                  {configuredProfile.tts_voice}
                </p>
              )}
              {stage.agent === "video" && configuredProfile?.subtitles_mode && (
                <p className="mb-2 text-[11px] text-zinc-500">
                  Subtítulos:{" "}
                  {configuredProfile.subtitles_mode === "none"
                    ? "no"
                    : configuredProfile.subtitles_mode === "srt"
                      ? "SRT descargable"
                      : "incrustados + SRT"}
                </p>
              )}
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
                        {p.name} (v{p.active_version} activa)
                        {p.orientation
                          ? ` · ${p.orientation === "vertical" ? "9:16" : "16:9"}`
                          : ""}
                        {p.slide_palette ? " · paleta" : ""}
                        {p.logo_mode && p.logo_mode !== "none" ? " · logo" : ""}
                        {p.tts_model ? ` · ${p.tts_model} · ${p.tts_voice}` : ""}
                        {p.subtitles_mode
                          ? ` · subtítulos ${
                              p.subtitles_mode === "none"
                                ? "no"
                                : p.subtitles_mode === "srt"
                                  ? "SRT"
                                  : "incrustados"
                            }`
                          : ""}
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
                  disabled={launchBlocked || missingInputs.length > 0 || needsDuration}
                  className="btn-secondary btn-sm shrink-0"
                  title={
                    needsDuration
                      ? "Configura antes la duración y estructura del proyecto"
                      : missingInputs.length > 0
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
            {activeRun.workflow_name && (
              <span className="text-xs text-zinc-400">
                {activeRun.workflow_name} · snapshot del run
              </span>
            )}
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
              {canPause && (
                <button
                  onClick={pause}
                  disabled={controlling}
                  className="btn-secondary btn-sm"
                >
                  <IconPause size={13} />
                  {controlling ? "Solicitando…" : "Pausar"}
                </button>
              )}
              {canResume && (
                <button
                  onClick={resume}
                  disabled={controlling}
                  className="btn-primary btn-sm"
                >
                  <IconPlay size={13} />
                  {controlling ? "Reanudando…" : "Reanudar"}
                </button>
              )}
              {canCancel && (
                <button
                  onClick={() => setConfirmCancel(true)}
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
                {activeRun.status === "pausing"
                  ? "Pausando cuando termine la operación actual…"
                  : activeRun.status === "canceling"
                    ? "Cancelando cuando termine la operación actual…"
                    : lastEvent
                  ? lastEvent.summary
                  : "Arrancando el agente, preparando contexto…"}
              </p>
            </div>
          )}

          {activeRun.status === "paused" && (
            <div className="border-b border-amber-400/20 bg-amber-500/[0.07] px-4 py-3">
              <p className="text-sm font-semibold text-amber-200">
                La ejecución está pausada y no se reanudará automáticamente.
              </p>
              <p className="mt-1 text-xs text-amber-100/70">
                {activeRun.control.checkpoint?.message ||
                  "Se conservaron el checkpoint y los artefactos completados."}
              </p>
              {activeRun.control.checkpoint?.next_unit && (
                <p className="mt-1 truncate font-mono text-[11px] text-amber-100/50">
                  Siguiente: {activeRun.control.checkpoint.next_unit}
                </p>
              )}
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
                El run está esperando tu revisión. Comprueba el último artefacto
                generado y decide.
              </p>
              <input
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Feedback para regenerar esta fase"
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
                      : "Escribe feedback para regenerar"
                  }
                  className="btn-danger"
                >
                  <IconX size={15} />
                  Enviar feedback y regenerar
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
                        {r.workflow_name
                          ? `${KIND_LABELS[r.kind] ?? r.kind} · ${r.workflow_name}`
                          : KIND_LABELS[r.kind] ?? r.kind}
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

      {artifactTypes.has("course_plan") && (
        <div className="card mb-5 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
                <IconVideo size={16} className="text-indigo-300" />
                Vídeo completo del curso
              </h3>
              <p className="mt-1 text-xs text-zinc-500">
                Une las versiones activas siguiendo exactamente el plan del curso,
                sin nuevas llamadas a IA ni TTS.
              </p>
            </div>
            {courseVideoPreflight && (
              <span
                className={
                  courseVideoPreflight.ready ? "badge-success" : "badge-warning"
                }
              >
                {courseVideoPreflight.ready
                  ? "Preflight superado"
                  : "Preflight pendiente"}
              </span>
            )}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <label className="flex items-center gap-2 text-sm text-zinc-300">
              <input
                type="checkbox"
                checked={courseVideoSubtitles ?? false}
                disabled={courseVideoSubtitles === null}
                onChange={(event) =>
                  setCourseVideoSubtitles(event.target.checked)
                }
              />
              Combinar SRT
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-300">
              <input
                type="checkbox"
                checked={courseVideoChapters}
                onChange={(event) =>
                  setCourseVideoChapters(event.target.checked)
                }
              />
              Incluir capítulos
            </label>
            <label className="text-xs text-zinc-400">
              Transición
              <select
                value={courseVideoTransition}
                onChange={(event) =>
                  setCourseVideoTransition(
                    event.target.value as CourseVideoTransition,
                  )
                }
                className="input mt-1"
              >
                <option value="none">Sin transición</option>
                <option value="fade_500ms">Fundido de 0,5 s</option>
                <option value="gap_500ms">Separación de 0,5 s</option>
              </select>
            </label>
          </div>

          {courseVideoPreflight && (
            <div className="mt-3 rounded-lg border border-zinc-700/70 bg-zinc-950/30 p-3">
              <p className="text-xs text-zinc-400">
                {courseVideoPreflight.lessons.length} lecciones ·{" "}
                {(courseVideoPreflight.output_duration_seconds / 60).toFixed(1)} min ·{" "}
                {courseVideoPreflight.orientation === "vertical"
                  ? "vertical 9:16"
                  : courseVideoPreflight.orientation === "horizontal"
                    ? "horizontal 16:9"
                    : "orientación sin resolver"}
              </p>
              {courseVideoPreflight.issues.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-amber-200">
                  {courseVideoPreflight.issues.map((issue, index) => (
                    <li key={`${issue.code}-${issue.lesson ?? index}`}>
                      {issue.lesson ? `${issue.lesson}: ` : ""}
                      {issue.detail}
                    </li>
                  ))}
                </ul>
              )}
              {courseVideoPreflight.lessons.length > 0 && (
                <details className="mt-2 text-xs text-zinc-400">
                  <summary className="cursor-pointer text-zinc-300">
                    Ver orden e inputs seleccionados
                  </summary>
                  <ol className="mt-2 space-y-1">
                    {courseVideoPreflight.lessons.map((lesson) => (
                      <li key={lesson.label}>
                        {lesson.label} ·{" "}
                        {lesson.video_artifact_id
                          ? `vídeo v${lesson.video_version}`
                          : "sin vídeo"}
                        {lesson.subtitles_artifact_id ? " · SRT" : " · sin SRT"}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn-primary"
              disabled={
                launchBlocked ||
                startingCourseVideo ||
                loadingCourseVideoPreflight ||
                !courseVideoPreflight?.ready
              }
              onClick={() => void startCourseVideo()}
            >
              {startingCourseVideo
                ? "Iniciando…"
                : loadingCourseVideoPreflight
                  ? "Comprobando…"
                  : "Generar vídeo completo"}
            </button>
            {courseVideoPreflight &&
              !courseVideoPreflight.subtitles_available && (
                <span className="text-xs text-zinc-500">
                  El SRT se activa solo cuando todas las lecciones tienen uno
                  seleccionado.
                </span>
              )}
          </div>
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
                : [filteredArtifacts.length, artifacts.length].join(" de ")}
            </span>
          )}
        </h3>
        <div className="flex items-center gap-2">
          <select
            value={artifactFilter}
            onChange={(event) => setArtifactFilter(event.target.value)}
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
          <button
            type="button"
            onClick={() => setShowUpload((value) => !value)}
            className="btn-secondary btn-sm"
          >
            <IconUpload size={13} />
            Subir propio
          </button>
        </div>
      </div>

      {(artifactTypes.has("slide_deck") ||
        artifactTypes.has("lesson_content")) && (
        <div className="card mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 p-3">
          {artifactTypes.has("slide_deck") && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-zinc-300">Slides:</span>
              <a
                href={"/api/projects/" + projectId + "/exports/slides.zip"}
                className="btn-secondary btn-sm"
              >
                ZIP
              </a>
              <a
                href={"/api/projects/" + projectId + "/exports/slides.pdf"}
                className="btn-secondary btn-sm"
              >
                PDF único
              </a>
              <button
                type="button"
                onClick={() => void downloadSlidesPptx()}
                disabled={exportingSlidesPptx}
                className="btn-secondary btn-sm"
              >
                {exportingSlidesPptx ? "Generando PPTX…" : "PPTX único"}
              </button>
            </div>
          )}
          {artifactTypes.has("lesson_content") && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-zinc-300">
                Lecciones:
              </span>
              <a
                href={"/api/projects/" + projectId + "/exports/lessons.zip"}
                className="btn-secondary btn-sm"
              >
                ZIP de PDFs
              </a>
              <a
                href={"/api/projects/" + projectId + "/exports/lessons.pdf"}
                className="btn-secondary btn-sm"
              >
                PDF único
              </a>
            </div>
          )}
          <span className="ml-auto text-[11px] text-zinc-500">
            Se incluyen únicamente las versiones activas.
          </span>
        </div>
      )}

      {showUpload && (
        <div className="card animate-in mb-4 flex flex-wrap items-end gap-3 p-4">
          <label className="min-w-52 text-xs text-zinc-400">
            Tipo del artefacto
            <select
              value={uploadType}
              onChange={(event) => setUploadType(event.target.value)}
              className="input mt-1"
            >
              {UPLOAD_TYPES.map((type) => (
                <option key={type} value={type}>
                  {TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </label>
          <label className="btn-primary cursor-pointer">
            <IconUpload size={13} />
            {uploading ? "Subiendo…" : "Elegir fichero"}
            <input
              ref={fileRef}
              type="file"
              accept=".md,.json,.txt,.pptx"
              disabled={uploading}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  void upload(file).then(() => setShowUpload(false));
                }
              }}
            />
          </label>
          <button
            type="button"
            onClick={() => setShowUpload(false)}
            disabled={uploading}
            className="btn-ghost btn-sm"
          >
            Cancelar
          </button>
          <p className="w-full text-xs text-zinc-500">
            El tipo se elige aquí porque forma parte de la subida, no del filtro
            de la biblioteca.
          </p>
        </div>
      )}

      {artifacts.length === 0 ? (
        <div className="card border-dashed p-8 text-center">
          <p className="flex items-center justify-center gap-2 text-sm text-zinc-400">
            <IconSparkles size={15} className="text-indigo-300" />
            Todavía no hay artefactos: ejecuta un agente o sube material propio.
          </p>
        </div>
      ) : filteredArtifacts.length === 0 ? (
        <div className="card border-dashed p-6 text-center text-sm text-zinc-500">
          No hay artefactos del tipo seleccionado.
        </div>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {filteredArtifacts.map((artifact) => {
            const producerRun = artifact.created_by_job_id
              ? runs.find((run) => run.id === artifact.created_by_job_id)
              : undefined;
            const producerLabel = producerRun
              ? KIND_LABELS[producerRun.kind] ?? producerRun.kind
              : artifact.created_by_job_id
                ? "Job"
                : null;
            const duration = durationLabel(artifact.metadata.duration_seconds);
            const cardActions = contextualArtifactActions(
              artifact.type,
              artifactTypes,
            );
            const primaryAction =
              cardActions.find(
                (action) => action.missing.length === 0 && !action.regenerates,
              ) ??
              cardActions.find((action) => action.missing.length === 0) ??
              null;
            const secondaryActions = cardActions.filter(
              (action) => action !== primaryAction,
            );
            const hasCourseVideoAction = artifact.type === "video";
            return (
              <li key={artifact.id}>
                <div className="card card-hover flex flex-wrap items-center gap-2 px-3 py-3 text-sm">
                  <Link
                    href={"/artifacts/" + artifact.id}
                    className="flex min-w-0 flex-1 items-center gap-3"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-zinc-300 bg-[#f4ead7] text-indigo-500">
                      {artifactIcon(artifact.type)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="mb-1 flex flex-wrap items-center gap-1.5">
                        <span className="badge-neutral">
                          {TYPE_LABELS[artifact.type] ?? artifact.type}
                        </span>
                        <span className="badge-success">Activa · v{artifact.version}</span>
                      </span>
                      <span className="block truncate font-medium text-zinc-200">
                        {artifact.title || artifact.type}
                      </span>
                      <span className="block text-xs text-zinc-500">
                        <time
                          dateTime={artifact.created_at}
                          title={new Date(artifact.created_at).toISOString()}
                        >
                          {new Date(artifact.created_at).toLocaleString("es")}
                        </time>
                        {orientationLabel(artifact.metadata)
                          ? ` · ${orientationLabel(artifact.metadata)}`
                          : ""}
                        {duration ? ` · ${duration}` : ""}
                        {paletteLabel(artifact.metadata)
                          ? ` · ${paletteLabel(artifact.metadata)}`
                          : ""}
                      </span>
                      {producerLabel && artifact.created_by_job_id && (
                        <span
                          className="block truncate text-[11px] text-zinc-600"
                          title={artifact.created_by_job_id}
                        >
                          {producerLabel} · job {artifact.created_by_job_id.slice(0, 8)}
                        </span>
                      )}
                    </span>
                  </Link>
                  {primaryAction && (
                    <button
                      type="button"
                      className="btn-secondary btn-sm shrink-0"
                      disabled={
                        launchBlocked ||
                        primaryAction.missing.length > 0 ||
                        (!durationConfigured &&
                          primaryAction.agent !== "curator")
                      }
                      title="Usará todas las versiones activas de los inputs"
                      onClick={() =>
                        setPendingArtifactAction({
                          kind: "agent",
                          action: primaryAction,
                          sourceArtifactId: artifact.id,
                          requestId: crypto.randomUUID(),
                        })
                      }
                    >
                      <IconPlay size={12} />
                      {artifactActionLabel(primaryAction)}
                    </button>
                  )}
                  {(secondaryActions.length > 0 || hasCourseVideoAction) && (
                    <details className="relative shrink-0">
                      <summary className="btn-ghost btn-sm cursor-pointer list-none">
                        Acciones
                      </summary>
                      <div className="absolute right-0 z-20 mt-1 w-72 space-y-1 rounded-lg border border-zinc-700 bg-zinc-950 p-2 shadow-xl">
                        {secondaryActions.map((action) => {
                          const needsDuration =
                            !durationConfigured && action.agent !== "curator";
                          const disabled =
                            launchBlocked ||
                            action.missing.length > 0 ||
                            needsDuration;
                          return (
                            <button
                              key={action.agent}
                              type="button"
                              className="btn-ghost w-full justify-start text-left text-xs"
                              disabled={disabled}
                              title={
                                needsDuration
                                  ? "Configura antes la duración y estructura del proyecto"
                                  : action.missing.length > 0
                                    ? `Antes necesitas: ${action.missing
                                        .map((type) => TYPE_LABELS[type] ?? type)
                                        .join(", ")}`
                                    : "Usará todas las versiones activas de los inputs"
                              }
                              onClick={() =>
                                setPendingArtifactAction({
                                  kind: "agent",
                                  action,
                                  sourceArtifactId: artifact.id,
                                  requestId: crypto.randomUUID(),
                                })
                              }
                            >
                              {artifactActionLabel(action)}
                              {action.missing.length > 0 && (
                                <span className="ml-1 text-zinc-600">
                                  · faltan{" "}
                                  {action.missing
                                    .map((type) => TYPE_LABELS[type] ?? type)
                                    .join(", ")}
                                </span>
                              )}
                            </button>
                          );
                        })}
                        {hasCourseVideoAction && (
                          <button
                            type="button"
                            className="btn-ghost w-full justify-start text-left text-xs"
                            disabled={
                              launchBlocked ||
                              loadingCourseVideoPreflight ||
                              !courseVideoPreflight?.ready
                            }
                            title={
                              courseVideoPreflight?.ready
                                ? "Usará los vídeos activos en orden pedagógico"
                                : "Completa los vídeos requeridos por el plan del curso"
                            }
                            onClick={() =>
                              setPendingArtifactAction({
                                kind: "course_video",
                                sourceArtifactId: artifact.id,
                                requestId: crypto.randomUUID(),
                              })
                            }
                          >
                            {artifactTypes.has("course_video")
                              ? "Regenerar vídeo completo"
                              : "Generar vídeo completo"}
                          </button>
                        )}
                      </div>
                    </details>
                  )}
                  <select
                    value={artifact.id}
                    onChange={(event) => chooseArtifact(event.target.value)}
                    className="input max-w-32 shrink-0 px-2 py-1.5 text-xs"
                    aria-label={
                      "Versión activa de " + (artifact.title || artifact.type)
                    }
                    title="La versión elegida será la que consuman los siguientes agentes"
                  >
                    {artifact.versions.map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version}
                        {orientationLabel(version.metadata)
                          ? ` · ${orientationLabel(version.metadata)}`
                          : ""}
                        {paletteLabel(version.metadata)
                          ? ` · ${paletteLabel(version.metadata)}`
                          : ""}
                        {version.is_selected ? " · activa" : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setArtifactToDelete(artifact)}
                    className="btn-ghost btn-sm shrink-0 text-red-300 hover:text-red-200"
                    aria-label={
                      "Eliminar versión " +
                      artifact.version +
                      " de " +
                      (artifact.title || artifact.type)
                    }
                    title={"Eliminar la versión activa v" + artifact.version}
                  >
                    <IconTrash size={14} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <ConfirmDialog
        open={pendingArtifactAction !== null}
        tone="default"
        title={
          pendingArtifactAction?.kind === "agent"
            ? artifactActionLabel(pendingArtifactAction.action)
            : artifactTypes.has("course_video")
              ? "Regenerar vídeo completo"
              : "Generar vídeo completo"
        }
        description={
          <div className="space-y-3">
            <p>
              La fase volverá a validar y congelar las versiones activas al
              iniciar. Si la selección cambia antes del POST, no se lanzará el
              job.
            </p>
            {pendingAgent && (
              <p className="rounded-md border border-white/[0.06] bg-white/[0.03] p-2 text-xs">
                Perfil:{" "}
                <strong className="text-zinc-100">
                  {pendingProfile
                    ? `${pendingProfile.name} · v${pendingProfile.active_version} activa`
                    : "perfil predeterminado"}
                </strong>
              </p>
            )}
            {pendingInputArtifacts.length > 0 ? (
              <ul className="space-y-1 text-xs text-zinc-400">
                {pendingInputArtifacts.map((input) => (
                  <li key={input.id}>
                    <Link
                      href={`/artifacts/${input.id}`}
                      className="text-indigo-300 hover:underline"
                    >
                      {TYPE_LABELS[input.type] ?? input.type} · v{input.version} ·{" "}
                      {input.title || input.id.slice(0, 8)}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-zinc-500">
                Esta fase usa el contexto del proyecto y no requiere artefactos
                previos.
              </p>
            )}
            <p className="text-xs text-zinc-500">
              Un resultado nuevo creará otra versión. Si el job falla o se
              cancela, la selección anterior seguirá activa.
            </p>
          </div>
        }
        confirmLabel="Iniciar fase"
        busyLabel="Iniciando…"
        busy={startingArtifactAction}
        onCancel={() => setPendingArtifactAction(null)}
        onConfirm={() => void confirmArtifactAction()}
      />
      <ConfirmDialog
        open={confirmCancel}
        title="Cancelar ejecución"
        description="La cancelación es terminal. La operación actual podrá terminar, pero no se iniciará la siguiente; los artefactos completos se conservarán."
        confirmLabel="Cancelar ejecución"
        busyLabel="Cancelando…"
        busy={cancelling}
        onCancel={() => setConfirmCancel(false)}
        onConfirm={cancel}
      />
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
