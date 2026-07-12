"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, type Project } from "@/lib/api";
import ProjectForm from "@/components/ProjectForm";
import CuratorRunner from "@/components/CuratorRunner";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .getProject(id)
      .then(setProject)
      .catch(() => setNotFound(true));
  }, [id]);

  async function handleDelete() {
    if (!confirm("¿Eliminar este proyecto? Esta acción no se puede deshacer.")) {
      return;
    }
    await api.deleteProject(id);
    router.push("/");
  }

  if (notFound) {
    return (
      <main className="mx-auto max-w-2xl p-6">
        <p className="text-neutral-400">Proyecto no encontrado.</p>
        <Link href="/" className="text-sm text-indigo-400 hover:underline">
          ← Volver al panel
        </Link>
      </main>
    );
  }

  if (!project) {
    return (
      <main className="mx-auto max-w-2xl p-6 text-neutral-400">Cargando…</main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/" className="text-sm text-indigo-400 hover:underline">
          ← Volver al panel
        </Link>
        <button
          onClick={handleDelete}
          className="rounded-lg border border-red-900 px-3 py-1.5 text-sm text-red-400 hover:bg-red-950"
        >
          Eliminar
        </button>
      </div>
      <h1 className="mb-6 text-2xl font-semibold">{project.title}</h1>
      <ProjectForm
        initial={project}
        submitLabel="Guardar cambios"
        onSubmit={async (input) => {
          const updated = await api.updateProject(id, input);
          setProject(updated);
          setSaved(true);
          setTimeout(() => setSaved(false), 2000);
        }}
      />
      {saved && <p className="mt-3 text-sm text-emerald-400">Guardado ✓</p>}
      <CuratorRunner projectId={id} />
    </main>
  );
}
