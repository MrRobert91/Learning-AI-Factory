"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type AgentProfile,
  type Artifact,
  type Job,
  type JobEvent,
} from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  queued: "En cola",
  running: "Ejecutando",
  done: "Completado",
  failed: "Fallido",
};

function EventLine({ event }: { event: JobEvent }) {
  const icon =
    event.type === "tool_call" ? "🔧" : event.type === "artifact" ? "📄" : "💬";
  return (
    <li className="flex gap-2 text-sm">
      <span>{icon}</span>
      <span className="whitespace-pre-wrap break-all text-neutral-300">
        {event.summary}
      </span>
    </li>
  );
}

export default function CuratorRunner({ projectId }: { projectId: string }) {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [profileId, setProfileId] = useState<string>("");
  const [runs, setRuns] = useState<Job[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [activeRun, setActiveRun] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    const [runList, artifactList] = await Promise.all([
      api.listProjectRuns(projectId),
      api.listProjectArtifacts(projectId),
    ]);
    setRuns(runList);
    setArtifacts(artifactList);
  }, [projectId]);

  useEffect(() => {
    api
      .listProfiles("curator")
      .then((list) => {
        setProfiles(list);
        const def = list.find((p) => p.is_default);
        if (def) setProfileId(def.id);
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
    source.onerror = () => {
      source.close();
    };
  }

  async function start() {
    setError(null);
    try {
      const job = await api.createCuratorRun(projectId, profileId || undefined);
      await refresh();
      follow(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo lanzar");
    }
  }

  const running = activeRun?.status === "queued" || activeRun?.status === "running";

  return (
    <section className="mt-10">
      <h2 className="mb-1 text-lg font-medium">Fábrica</h2>
      <p className="mb-4 text-sm text-neutral-400">
        Lanza el Curador de contenido para investigar el tema y generar el
        research brief del curso.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          value={profileId}
          onChange={(e) => setProfileId(e.target.value)}
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        >
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} (v{p.version})
            </option>
          ))}
        </select>
        <button
          onClick={start}
          disabled={running}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
        >
          {running ? "Investigando…" : "🔍 Ejecutar Curador"}
        </button>
        <Link
          href="/profiles"
          className="text-sm text-indigo-400 hover:underline"
        >
          Editar perfiles
        </Link>
      </div>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      {activeRun && (
        <div className="mb-6 rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">
              Ejecución del Curador — {STATUS_LABELS[activeRun.status]}
            </span>
            {running && (
              <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-400" />
            )}
          </div>
          {activeRun.status === "failed" && (
            <p className="mb-2 text-sm text-red-400">{activeRun.error}</p>
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
        <ul className="mb-6 space-y-2">
          {runs.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => follow(r)}
                className="flex w-full items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm transition hover:border-neutral-600"
              >
                <span>Curador · {new Date(r.created_at).toLocaleString("es")}</span>
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
      )}

      <h3 className="mb-2 text-base font-medium">Artefactos</h3>
      {artifacts.length === 0 ? (
        <p className="text-sm text-neutral-500">
          Todavía no hay artefactos generados.
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
                  <span className="ml-2 text-xs text-neutral-500">{a.type}</span>
                </span>
                <span className="text-xs text-neutral-500">
                  {new Date(a.created_at).toLocaleString("es")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
