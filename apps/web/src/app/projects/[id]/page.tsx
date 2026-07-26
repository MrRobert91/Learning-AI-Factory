"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, type Project } from "@/lib/api";
import ProjectForm from "@/components/ProjectForm";
import FactoryPanel from "@/components/FactoryPanel";
import WikiPanel from "@/components/WikiPanel";
import {
  ConfirmDialog,
  EmptyState,
  IconChevronLeft,
  IconFileText,
  IconFolder,
  LoadingScreen,
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

const RESEARCH_MODE_LABELS = {
  web_only: "Investigación web libre",
  provided_plus_web: "Fuentes proporcionadas + web",
  provided_only: "Solo fuentes proporcionadas",
};

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    api
      .getProject(id)
      .then(setProject)
      .catch(() => setNotFound(true));
  }, [id]);

  async function handleDelete() {
    setDeleting(true);
    await api.deleteProject(id);
    router.push("/");
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16">
        <EmptyState
          icon={<IconFolder size={22} />}
          title="Proyecto no encontrado"
          description="Puede que se haya eliminado o que el enlace no sea correcto."
          action={
            <Link href="/" className="btn-secondary">
              <IconChevronLeft size={15} />
              Volver a proyectos
            </Link>
          }
        />
      </div>
    );
  }

  if (!project) {
    return <LoadingScreen label="Cargando proyecto…" />;
  }

  const badge = STATUS_BADGE[project.status] ?? {
    label: project.status,
    className: "badge-neutral",
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-5">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Proyectos
        </Link>
      </div>

      <header className="mb-2 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">
              {project.title}
            </h1>
            <span className={badge.className}>{badge.label}</span>
          </div>
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-sm text-zinc-500">
            {project.audience && <span>Audiencia: {project.audience}</span>}
            {project.level && (
              <span>Nivel: {LEVEL_LABELS[project.level] ?? project.level}</span>
            )}
            <span>Idioma: {project.language === "en" ? "Inglés" : "Español"}</span>
            {project.duration_spec && (
              <span>
                {project.duration_spec.total_videos} vídeos ·{" "}
                {project.duration_spec.total_minutes} min
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSettings((v) => !v)}
            className="btn-secondary btn-sm"
          >
            {showSettings ? "Ocultar configuración" : "Editar configuración"}
          </button>
          <button onClick={() => setConfirmDelete(true)} className="btn-danger btn-sm">
            Eliminar
          </button>
        </div>
      </header>

      {project.topic && (
        <p className="mb-4 max-w-3xl text-sm leading-relaxed text-zinc-400">
          {project.topic}
        </p>
      )}

      {!project.duration_spec && (
        <button
          type="button"
          onClick={() => setShowSettings(true)}
          className="mb-6 w-full rounded-xl border border-amber-400/30 bg-amber-500/[0.07] p-4 text-left"
        >
          <span className="block text-sm font-semibold text-amber-200">
            Completa la duración y estructura del curso
          </span>
          <span className="mt-1 block text-sm text-amber-100/70">
            Este proyecto es anterior a la configuración estructurada. Elige un
            preset o valores personalizados para desbloquear planner y las fases
            posteriores.
          </span>
        </button>
      )}

      {showSettings && (
        <section className="card animate-in mb-6 p-6">
          <h2 className="mb-1 text-base font-semibold text-zinc-100">
            Configuración del proyecto
          </h2>
          <p className="mb-5 text-sm text-zinc-400">
            Estos datos alimentan el prompt de todos los agentes de este curso.
          </p>
          <ProjectForm
            initial={project}
            submitLabel="Guardar cambios"
            onSubmit={async (input) => {
              const updated = await api.updateProject(id, input);
              setProject(updated);
              setSaved(true);
              setTimeout(() => setSaved(false), 2500);
            }}
          />
          {saved && (
            <p className="animate-in mt-3 text-sm text-emerald-400">
              Cambios guardados ✓
            </p>
          )}
        </section>
      )}

      <section className="card mb-6 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">
              Fuentes de investigación
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              {RESEARCH_MODE_LABELS[project.research_mode]}
            </p>
          </div>
          <span className="badge-neutral">
            {project.sources.length} fuentes
          </span>
        </div>
        {project.sources.length > 0 ? (
          <ul className="mt-4 grid gap-2 sm:grid-cols-2">
            {project.sources.map((source) => (
              <li
                key={source.id}
                className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3"
              >
                <div className="flex gap-2">
                  <IconFileText size={14} className="mt-0.5 text-indigo-300" />
                  <div className="min-w-0">
                    <p className="truncate text-sm text-zinc-300">
                      {source.name}
                    </p>
                    <p className="mt-0.5 text-[10px] text-zinc-600">
                      {source.kind.toUpperCase()} · {source.sha256.slice(0, 12)}
                    </p>
                    <p className="mt-2 flex gap-3 text-xs">
                      <a
                        href={`/api/ideation/sources/${source.id}/original`}
                        className="text-indigo-300 hover:underline"
                      >
                        Descargar original
                      </a>
                      <a
                        href={`/api/ideation/sources/${source.id}/text`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-300 hover:underline"
                      >
                        Ver texto
                      </a>
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-xs text-zinc-600">
            Este proyecto no tiene un corpus proporcionado.
          </p>
        )}
      </section>

      <FactoryPanel
        projectId={id}
        durationConfigured={project.duration_spec !== null}
      />
      <WikiPanel projectId={id} />
      <ConfirmDialog
        open={confirmDelete}
        title="Eliminar proyecto"
        description={`Se eliminará «${project.title}» junto con sus ejecuciones y artefactos. Esta acción no se puede deshacer.`}
        busy={deleting}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
