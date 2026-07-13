"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type Project } from "@/lib/api";
import ProjectForm from "@/components/ProjectForm";
import {
  EmptyState,
  IconFolder,
  IconPlus,
  IconSparkles,
  IconX,
  LoadingScreen,
  PageHeader,
} from "@/components/ui";

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  draft: { label: "Borrador", className: "badge-neutral" },
  active: { label: "Activo", className: "badge-success" },
  archived: { label: "Archivado", className: "badge-neutral" },
};

const LEVEL_LABELS: Record<string, string> = {
  introductorio: "Introductorio",
  intermedio: "Intermedio",
  avanzado: "Avanzado",
};

function relativeDate(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "hace un momento";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `hace ${days} d`;
  return new Date(iso).toLocaleDateString("es");
}

export default function DashboardPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    setProjects(await api.listProjects());
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <PageHeader
        title="Proyectos"
        description="Cada proyecto es un curso en fabricación: desde la investigación inicial hasta el vídeo publicado."
        actions={
          <>
            <button
              onClick={() => setShowForm((v) => !v)}
              className="btn-secondary"
            >
              {showForm ? <IconX size={15} /> : <IconPlus size={15} />}
              {showForm ? "Cancelar" : "Proyecto manual"}
            </button>
            <Link href="/ideation" className="btn-primary">
              <IconSparkles size={15} />
              Nueva idea con asistente
            </Link>
          </>
        }
      />

      {showForm && (
        <section className="card animate-in mb-8 p-6">
          <h2 className="mb-1 text-base font-semibold text-zinc-100">
            Nuevo proyecto manual
          </h2>
          <p className="mb-5 text-sm text-zinc-400">
            Si ya tienes clara la idea, define aquí el curso directamente. Si
            prefieres afinarla conversando, usa el asistente de ideación.
          </p>
          <ProjectForm
            submitLabel="Crear proyecto"
            onSubmit={async (input) => {
              const project = await api.createProject(input);
              setShowForm(false);
              router.push(`/projects/${project.id}`);
            }}
          />
        </section>
      )}

      {projects === null ? (
        <LoadingScreen label="Cargando proyectos…" />
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<IconFolder size={22} />}
          title="Todavía no tienes proyectos"
          description="Empieza con el asistente de ideación: convierte una idea vaga en un brief listo para fabricar el curso."
          action={
            <Link href="/ideation" className="btn-primary">
              <IconSparkles size={15} />
              Empezar con una idea
            </Link>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((p, i) => {
            const badge = STATUS_BADGE[p.status] ?? {
              label: p.status,
              className: "badge-neutral",
            };
            return (
              <li key={p.id} className="animate-in" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
                <Link
                  href={`/projects/${p.id}`}
                  className="card card-hover flex h-full flex-col p-5"
                >
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <span className="min-w-0 truncate text-[15px] font-semibold text-zinc-100">
                      {p.title}
                    </span>
                    <span className={`${badge.className} shrink-0`}>{badge.label}</span>
                  </div>
                  <p className="mb-4 line-clamp-2 min-h-10 flex-1 text-sm leading-relaxed text-zinc-400">
                    {p.topic || "Sin descripción del tema."}
                  </p>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/[0.06] pt-3 text-xs text-zinc-500">
                    {p.audience && (
                      <span className="min-w-0 truncate" title={p.audience}>
                        {p.audience}
                      </span>
                    )}
                    {p.level && <span>{LEVEL_LABELS[p.level] ?? p.level}</span>}
                    <span className="ml-auto shrink-0">
                      {relativeDate(p.updated_at)}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
