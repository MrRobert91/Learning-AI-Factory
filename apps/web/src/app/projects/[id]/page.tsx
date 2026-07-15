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

      <FactoryPanel projectId={id} />
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
