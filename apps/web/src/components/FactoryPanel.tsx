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

const STATUS_LABELS: Record<string, string> = {
  queued: "En cola",
  running: "Ejecutando",
  waiting_approval: "Esperando tu aprobación",
  done: "Completado",
  failed: "Fallido",
};

const STAGES: { agent: string; label: string; produces: string }[] = [
  { agent: "curator", label: "① Curador", produces: "research_brief" },
  { agent: "planner", label: "② Plan del curso", produces: "course_plan" },
  { agent: "lessons", label: "③ Lecciones", produces: "lesson_content" },
  { agent: "slides", label: "④ Slides", produces: "slide_deck" },
  { agent: "script", label: "⑤ Guion docente", produces: "teaching_script" },
  { agent: "voice", label: "⑥ Adaptación a voz", produces: "voice_script" },
  { agent: "video", label: "⑦ Vídeo", produces: "video" },
  { agent: "publisher", label: "⑧ Publicación", produces: "publication_package" },
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
  lesson_content: "Lecciones",
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

function EventLine({ event }: { event: JobEvent }) {
  const icon =
    event.type === "tool_call"
      ? "🔧"
      : event.type === "artifact"
        ? "📄"
        : event.type === "stage"
          ? "▶"
          : event.type === "evaluation"
            ? "🧪"
            : event.type === "memory"
              ? "🧠"
              : "💬";
  return (
    <li className="flex gap-2 text-sm">
      <span>{icon}</span>
      <span className="whitespace-pre-wrap break-all text-neutral-300">
        {event.summary}
      </span>
    </li>
  );
}

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
  const [uploading, setUploading] = useState(false);
  const [uploadType, setUploadType] = useState("slide_deck");
  const sourceRef = useRef<EventSource | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const [runList, artifactList] = await Promise.all([
      api.listProjectRuns(projectId),
      api.listProjectArtifacts(projectId),
    ]);
    setRuns(runList);
    setArtifacts(artifactList);
  }, [projectId]);

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
    refresh().catch(() => {});
    return () => sourceRef.current?.close();
  }, [projectId, refresh]);

  function follow(job: Job) {
    setActiveRun(job);
    setEvents(job.events ?? []);
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
  }

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

  const running =
    activeRun?.status === "queued" || activeRun?.status === "running";
  const artifactTypes = new Set(artifacts.map((a) => a.type));

  return (
    <section className="mt-10">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">Fábrica</h2>
          <p className="text-sm text-neutral-400">
            Lanza un workflow completo o ejecuta agentes sueltos por etapas.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
            className="max-w-56 rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-2 text-sm outline-none focus:border-indigo-500"
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <button
            onClick={startWorkflow}
            disabled={running || !workflowId}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
          >
            🏭 Ejecutar workflow
          </button>
          <button
            onClick={startAnalytics}
            disabled={running}
            title="Analiza métricas y comentarios de los vídeos publicados de este proyecto"
            className="rounded-lg border border-neutral-700 px-3 py-2 text-sm text-neutral-300 hover:bg-neutral-900 disabled:opacity-50"
          >
            📈 Analizar rendimiento
          </button>
          <Link
            href="/workflows"
            className="text-sm text-indigo-400 hover:underline"
          >
            Editar
          </Link>
        </div>
      </div>

      <div className="mb-6 grid gap-3 sm:grid-cols-2">
        {STAGES.map((stage) => (
          <div
            key={stage.agent}
            className="rounded-xl border border-neutral-800 p-3"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">{stage.label}</span>
              {artifactTypes.has(stage.produces) && (
                <span className="text-xs text-emerald-400">✓ hecho</span>
              )}
            </div>
            <div className="flex gap-2">
              {(profilesByAgent[stage.agent] ?? []).length > 0 ? (
                <select
                  value={selectedProfile[stage.agent] ?? ""}
                  onChange={(e) =>
                    setSelectedProfile((prev) => ({
                      ...prev,
                      [stage.agent]: e.target.value,
                    }))
                  }
                  className="min-w-0 flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs outline-none focus:border-indigo-500"
                >
                  {(profilesByAgent[stage.agent] ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} (v{p.version})
                    </option>
                  ))}
                </select>
              ) : (
                <span className="flex-1 self-center text-xs text-neutral-500">
                  TTS + ffmpeg (sin perfil)
                </span>
              )}
              <button
                onClick={() => start(stage.agent)}
                disabled={running}
                className="rounded-lg border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-900 disabled:opacity-50"
              >
                Ejecutar
              </button>
            </div>
          </div>
        ))}
      </div>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      {activeRun && (
        <div className="mb-6 rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">
              {activeRun.kind === "workflow_run"
                ? "Workflow"
                : activeRun.kind === "pipeline_run"
                  ? "Pipeline"
                  : "Agente"}{" "}
              — {STATUS_LABELS[activeRun.status]}
            </span>
            <div className="flex items-center gap-3">
              {running && (
                <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-400" />
              )}
              <button
                onClick={() => setActiveRun(null)}
                className="text-xs text-neutral-500 hover:text-neutral-300"
              >
                cerrar
              </button>
            </div>
          </div>
          {activeRun.status === "failed" && (
            <p className="mb-2 text-sm text-red-400">{activeRun.error}</p>
          )}
          {activeRun.status === "waiting_approval" && (
            <div className="mb-3 rounded-lg border border-amber-900/60 bg-amber-950/30 p-3">
              <p className="mb-2 text-sm text-amber-300">
                ✋ El workflow está pausado esperando tu revisión. Revisa el
                artefacto generado (lista de abajo) y decide.
              </p>
              <input
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Feedback opcional (obligatorio si rechazas)"
                className="mb-2 w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-amber-500"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => decide(true)}
                  disabled={deciding}
                  className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50"
                >
                  Aprobar y continuar
                </button>
                <button
                  onClick={() => decide(false)}
                  disabled={deciding || !feedback.trim()}
                  className="rounded-lg border border-red-900 px-4 py-1.5 text-sm text-red-400 hover:bg-red-950 disabled:opacity-50"
                >
                  Rechazar
                </button>
              </div>
            </div>
          )}
          <ul className="max-h-64 space-y-1 overflow-y-auto">
            {events.map((e) => (
              <EventLine key={e.seq} event={e} />
            ))}
            {events.length === 0 && (
              <li className="text-sm text-neutral-500">Arrancando agente…</li>
            )}
          </ul>
        </div>
      )}

      {runs.length > 0 && !activeRun && (
        <details className="mb-6">
          <summary className="cursor-pointer text-sm text-neutral-400">
            Historial de ejecuciones ({runs.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {runs.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => follow(r)}
                  className="flex w-full items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm transition hover:border-neutral-600"
                >
                  <span>
                    {r.kind.replace("_run", "")} ·{" "}
                    {new Date(r.created_at).toLocaleString("es")}
                  </span>
                  <span
                    className={
                      r.status === "done"
                        ? "text-emerald-400"
                        : r.status === "failed"
                          ? "text-red-400"
                          : "text-neutral-400"
                    }
                  >
                    {STATUS_LABELS[r.status]}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-base font-medium">Artefactos</h3>
        <div className="flex items-center gap-2">
          <select
            value={uploadType}
            onChange={(e) => setUploadType(e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs outline-none"
          >
            {UPLOAD_TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
          <label className="cursor-pointer rounded-lg border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-900">
            {uploading ? "Subiendo…" : "⬆ Subir artefacto"}
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
        <p className="text-sm text-neutral-500">
          Todavía no hay artefactos. Ejecuta el Curador o sube material propio.
        </p>
      ) : (
        <ul className="space-y-2">
          {artifacts.map((a) => (
            <li key={a.id}>
              <Link
                href={`/artifacts/${a.id}`}
                className="flex items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm transition hover:border-neutral-600"
              >
                <span>
                  📄 {a.title || a.type}
                  <span className="ml-2 text-xs text-neutral-500">
                    {TYPE_LABELS[a.type] ?? a.type}
                  </span>
                </span>
                <span className="text-xs text-neutral-500">
                  {new Date(a.created_at).toLocaleString("es")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-neutral-600">
        <Link href="/profiles" className="text-indigo-400 hover:underline">
          Editar perfiles de agentes →
        </Link>
      </p>
    </section>
  );
}
