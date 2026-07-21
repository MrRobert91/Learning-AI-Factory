"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type AgentProfile, type AgentSpec } from "@/lib/api";
import {
  IconPlus,
  IconStar,
  LoadingScreen,
  PageHeader,
} from "@/components/ui";

const TYPE_LABELS: Record<string, string> = {
  course_idea_brief: "brief de idea",
  research_brief: "research brief",
  course_plan: "plan del curso",
  lesson_content: "lecciones",
  slide_deck: "slides",
  teaching_script: "guion docente",
  voice_script: "guion de voz",
  video: "vídeo",
  subtitles: "subtítulos",
  publication_package: "publicación",
  performance_report: "informe de rendimiento",
  improvement_proposal: "propuestas de mejora",
  thumbnail: "miniatura",
};

const EXECUTION_ORDER = [
  "ideation",
  "curator",
  "planner",
  "lessons",
  "slides",
  "script",
  "voice",
  "video",
  "publisher",
  "analyst",
];

const SOURCE_INPUTS: Record<string, string> = {
  ideation: "Idea inicial del usuario",
  curator: "Brief de idea y datos del proyecto",
  analyst: "Métricas y comentarios de YouTube",
};

export default function ProfilesPage() {
  const [agents, setAgents] = useState<AgentSpec[] | null>(null);
  const [profiles, setProfiles] = useState<Record<string, AgentProfile[]>>({});
  const [creating, setCreating] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    const specs = [...(await api.listAgents())].sort(
      (left, right) =>
        EXECUTION_ORDER.indexOf(left.name) - EXECUTION_ORDER.indexOf(right.name),
    );
    const byType: Record<string, AgentProfile[]> = {};
    await Promise.all(
      specs.map(async (s) => {
        byType[s.name] = await api.listProfiles(s.name);
      }),
    );
    setAgents(specs);
    setProfiles(byType);
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function createProfile(agentType: string) {
    if (!newName.trim()) return;
    await api.createProfile(agentType, { name: newName.trim() });
    setCreating(null);
    setNewName("");
    await load();
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <PageHeader
        title="Agentes y perfiles"
        description={
          <>
            Cada perfil conserva la configuración de una etapa. Los agentes de
            IA incluyen personalidad (<code>soul.md</code>) y reglas operativas (
            <code>agents.md</code>); Slides y Vídeo también permiten elegir la
            orientación, y Slides puede generar imágenes con un modelo y estilo
            consistentes. Puedes seleccionar un perfil distinto en cada ejecución.
          </>
        }
      />

      {agents === null ? (
        <LoadingScreen label="Cargando agentes…" />
      ) : (
        agents.map((agent, index) => (
          <section key={agent.name} className="card mb-5 p-5">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-500/[0.12] text-indigo-300">
                  <span className="text-xs font-bold">{index + 1}</span>
                </span>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-zinc-100">
                    {agent.display_name}
                  </h2>
                  <p className="text-sm leading-relaxed text-zinc-400">
                    {agent.description}
                  </p>
                  <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                    <div>
                      <span className="font-semibold uppercase tracking-wide text-zinc-500">
                        Input
                      </span>
                      <p className="mt-1 flex flex-wrap gap-1.5">
                        {agent.consumes.length > 0 ? (
                          agent.consumes.map((item) => (
                            <span key={item} className="badge-neutral">
                              {TYPE_LABELS[item] ?? item}
                            </span>
                          ))
                        ) : (
                          <span className="text-zinc-500">
                            {SOURCE_INPUTS[agent.name] ?? "Datos del proyecto"}
                          </span>
                        )}
                      </p>
                    </div>
                    <div>
                      <span className="font-semibold uppercase tracking-wide text-zinc-500">
                        Output esperado
                      </span>
                      <p className="mt-1 flex flex-wrap gap-1.5">
                        {agent.produces.map((item) => (
                          <span key={item} className="badge-info">
                            {TYPE_LABELS[item] ?? item}
                          </span>
                        ))}
                      </p>
                    </div>
                  </div>
                  {agent.tool_names.length > 0 && (
                    <p className="mt-2 text-xs text-zinc-500">
                      Herramientas: {agent.tool_names.join(", ")}
                    </p>
                  )}
                </div>
              </div>
              <button
                onClick={() => {
                  setCreating(creating === agent.name ? null : agent.name);
                  setNewName("");
                }}
                className="btn-secondary btn-sm shrink-0"
              >
                <IconPlus size={13} />
                Nuevo perfil
              </button>
            </div>
            {creating === agent.name && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  createProfile(agent.name);
                }}
                className="animate-in mb-3 flex gap-2"
              >
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  autoFocus
                  placeholder="Nombre del perfil (ej. Curador divulgativo)"
                  className="input flex-1"
                />
                <button type="submit" className="btn-primary btn-sm">
                  Crear
                </button>
              </form>
            )}
            <ul className="space-y-1.5">
                {(profiles[agent.name] ?? []).map((p) => (
                  <li key={p.id}>
                    <Link
                      href={`/profiles/${p.id}`}
                      className="card card-hover flex items-center gap-3 px-4 py-2.5 text-sm"
                    >
                      <span className="min-w-0 flex-1 truncate font-medium text-zinc-200">
                        {p.name}
                      </span>
                      {p.is_default && (
                        <span className="badge-info shrink-0">
                          <IconStar size={10} />
                          por defecto
                        </span>
                      )}
                      {p.orientation && (
                        <span className="badge-neutral shrink-0">
                          {p.orientation === "vertical"
                            ? "Vertical 9:16"
                            : "Horizontal 16:9"}
                        </span>
                      )}
                      {p.images_enabled !== null && (
                        <span
                          className={p.images_enabled ? "badge-info shrink-0" : "badge-neutral shrink-0"}
                        >
                          {p.images_enabled ? "Con imágenes" : "Sin imágenes"}
                        </span>
                      )}
                      <span className="shrink-0 text-xs text-zinc-500">
                        v{p.version}
                      </span>
                    </Link>
                  </li>
                ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
